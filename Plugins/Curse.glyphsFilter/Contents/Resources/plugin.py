# encoding: utf-8
from __future__ import division, print_function, unicode_literals

"""Curse: slant outlines, rebalance curves, and correct straight-stroke weight.

Curve endpoints move along their tangents, with limits from neighbouring
segments. Implicit extrema supply the bounds for incomplete arcs. Nearly
parallel tangents and excessive extrapolation are excluded. Straight-stroke
correction uses the perpendicular width measured in the upright outline.
"""

import objc
import math
from GlyphsApp import Glyphs, GSPath, LINE, CURVE, OFFCURVE
from GlyphsApp.plugins import FilterWithDialog
from AppKit import NSView, NSSlider, NSTextField, NSButton, NSMakeRect, NSFont, NSEvent
from Foundation import NSMakePoint

FLAT = 12         # polyline pieces per curve for ray casts
AXIS_TOL = 0.035  # |sin| below this counts as an axis-aligned tangent (~2 deg)
EXT_LIMIT = 4.0   # max extension in units of segment parameter
WIDTH_CAP = 1.5   # local half-width clamp (x median) for the line corrections
EXTREME_TOL = 2.0 # keep-extremes: max outline deviation allowed when re-placing a node
EXTREME_SLIDE = 0.45  # keep-extremes: max slide, as a fraction of the host segment's chord
CORNER_FAR = 1.5      # corner farther than this x chord = near-parallel tangents: no correction


# ---------------------------------------------------------------- geometry

def _unit(x, y):
	l = math.hypot(x, y)
	if l < 1e-9:
		return None
	return (x / l, y / l)


def _bez(C, t):
	mt = 1 - t
	return (mt**3 * C[0][0] + 3 * mt * mt * t * C[1][0] + 3 * mt * t * t * C[2][0] + t**3 * C[3][0],
		mt**3 * C[0][1] + 3 * mt * mt * t * C[1][1] + 3 * mt * t * t * C[2][1] + t**3 * C[3][1])


def _bezD(C, t):
	mt = 1 - t
	return (3 * (mt * mt * (C[1][0] - C[0][0]) + 2 * mt * t * (C[2][0] - C[1][0]) + t * t * (C[3][0] - C[2][0])),
		3 * (mt * mt * (C[1][1] - C[0][1]) + 2 * mt * t * (C[2][1] - C[1][1]) + t * t * (C[3][1] - C[2][1])))


def _sub(C, t0, t1):
    """Reparameterize a cubic over any finite interval, including reversed spans."""
    a, b = _bez(C, t0), _bez(C, t1)
    da, db = _bezD(C, t0), _bezD(C, t1)
    scale = (t1 - t0) / 3.0
    return (a, (a[0] + scale * da[0], a[1] + scale * da[1]),
            (b[0] - scale * db[0], b[1] - scale * db[1]), b)

def _rayInt(P, d1, Q, d2):
	den = d1[0] * d2[1] - d1[1] * d2[0]
	if abs(den) < 1e-9:
		return None
	qx, qy = Q[0] - P[0], Q[1] - P[1]
	a = (qx * d2[1] - qy * d2[0]) / den
	b = (qx * d1[1] - qy * d1[0]) / den
	return (P[0] + a * d1[0], P[1] + a * d1[1]), a, b


def _raySeg(P, d, a, b):
	ex, ey = b[0] - a[0], b[1] - a[1]
	den = d[0] * ey - d[1] * ex
	if abs(den) < 1e-12:
		return None
	qx, qy = a[0] - P[0], a[1] - P[1]
	s = (qx * ey - qy * ex) / den
	u = (qx * d[1] - qy * d[0]) / den
	if s <= 0 or u < -1e-6 or u > 1 + 1e-6:
		return None
	return s


def _median(vals):
	v = sorted(vals)
	n = len(v)
	if not n:
		return None
	return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _axisKind(t):
	"""'h' / 'v' if the unit tangent is (nearly) horizontal / vertical, else None."""
	if t is None:
		return None
	if abs(t[1]) <= AXIS_TOL:
		return 'h'
	if abs(t[0]) <= AXIS_TOL:
		return 'v'
	return None


def _extremeParams(C):
	"""All parameters where x'(t)=0 or y'(t)=0 for the cubic (any real t)."""
	out = []
	for axis in (0, 1):
		a = C[3][axis] - 3 * C[2][axis] + 3 * C[1][axis] - C[0][axis]
		b = 2 * (C[2][axis] - 2 * C[1][axis] + C[0][axis])
		c = C[1][axis] - C[0][axis]
		# derivative/3 = a t^2 + b t + c
		if abs(a) < 1e-12:
			if abs(b) > 1e-12:
				out.append(-c / b)
			continue
		disc = b * b - 4 * a * c
		if disc < 0:
			continue
		r = math.sqrt(disc)
		out.append((-b - r) / (2 * a))
		out.append((-b + r) / (2 * a))
	return out


def _inflections(C):
	"""Parameters where the cubic's curvature is zero: cross(D, D') = 0."""
	# D(t) = 3[(1-t)^2 a + 2(1-t)t b + t^2 c], with a=P1-P0, b=P2-P1, c=P3-P2
	ax, ay = C[1][0] - C[0][0], C[1][1] - C[0][1]
	bx, by = C[2][0] - C[1][0], C[2][1] - C[1][1]
	cx, cy = C[3][0] - C[2][0], C[3][1] - C[2][1]
	# cross(D, D') is quadratic in t: k0 + k1 t + k2 t^2 (up to a constant)
	# D = a + 2t(b-a) + t^2(a-2b+c);  D' = 2(b-a) + 2t(a-2b+c)
	ux, uy = bx - ax, by - ay
	vx, vy = ax - 2 * bx + cx, ay - 2 * by + cy
	# D = a + 2t u + t^2 v ; D' = 2u + 2t v
	# cross(D, D') = 2[cross(a,u) + t cross(a,v) + t^2 cross(u,v)]  (t^2 terms from cross(u,v) with 2t*t)
	k0 = ax * uy - ay * ux
	k1 = ax * vy - ay * vx
	k2 = ux * vy - uy * vx
	out = []
	if abs(k2) < 1e-12:
		if abs(k1) > 1e-12:
			out.append(-k0 / k1)
		return out
	disc = k1 * k1 - 4 * k2 * k0
	if disc < 0:
		return out
	r = math.sqrt(disc)
	out.append((-k1 - r) / (2 * k2))
	out.append((-k1 + r) / (2 * k2))
	return out


EXT_EXTERNAL_LIMIT = 1.0  # inflection ("external") extensions: at most one segment-length


def _extend(C, bounds=None):
	"""Extend a cubic beyond an end whose tangent is not axis-aligned:
	to the implicit extreme (x'=0 or y'=0) if one exists within EXT_LIMIT,
	otherwise to the inflection point (where the tangent stops approaching
	the axis) within EXT_EXTERNAL_LIMIT -- the "external extension". Either
	way the extended point must stay inside `bounds` (xmin, ymin, xmax, ymax)
	when given. Returns (t0, t1), t0<=0<=1<=t1."""
	t0, t1 = 0.0, 1.0
	dA = _unit(*_bezD(C, 0.0))
	dB = _unit(*_bezD(C, 1.0))
	roots = _extremeParams(C)
	infl = _inflections(C)

	def inside(t):
		if bounds is None:
			return True
		x, y = _bez(C, t)
		return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]

	if _axisKind(dA) is None:
		cands = [r for r in roots if r < -1e-6 and r >= -EXT_LIMIT and inside(r)]
		if cands:
			t0 = max(cands)
		else:
			cands = [r for r in infl if r < -1e-6 and r >= -EXT_EXTERNAL_LIMIT and inside(r)]
			if cands:
				t0 = max(cands)
	if _axisKind(dB) is None:
		cands = [r for r in roots if r > 1 + 1e-6 and r <= 1 + EXT_LIMIT and inside(r)]
		if cands:
			t1 = min(cands)
		else:
			cands = [r for r in infl if r > 1 + 1e-6 and r <= 1 + EXT_EXTERNAL_LIMIT and inside(r)]
			if cands:
				t1 = min(cands)
	return t0, t1


def _fitCubicFree(samples, p0, p3, t1, t2, iters=8):
	"""Least-squares cubic through samples with fixed endpoints and tangent
	directions (t1 forward from p0, t2 backward from p3), with Newton
	reparameterisation (Schneider). Returns control points or None."""
	if t1 is None or t2 is None:
		return None
	us = [0.0]
	for a, b in zip(samples, samples[1:]):
		us.append(us[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
	total = us[-1] or 1.0
	us = [u / total for u in us]
	best = None
	chord = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
	for _ in range(iters):
		C00 = C01 = C11 = X0 = X1 = 0.0
		for pt, u in zip(samples, us):
			mt = 1 - u
			b1, b2 = 3 * mt * mt * u, 3 * mt * u * u
			a1 = (t1[0] * b1, t1[1] * b1)
			a2 = (t2[0] * b2, t2[1] * b2)
			bx = p0[0] * (mt**3 + b1) + p3[0] * (b2 + u**3)
			by = p0[1] * (mt**3 + b1) + p3[1] * (b2 + u**3)
			tx, ty = pt[0] - bx, pt[1] - by
			C00 += a1[0] * a1[0] + a1[1] * a1[1]
			C01 += a1[0] * a2[0] + a1[1] * a2[1]
			C11 += a2[0] * a2[0] + a2[1] * a2[1]
			X0 += a1[0] * tx + a1[1] * ty
			X1 += a2[0] * tx + a2[1] * ty
		det = C00 * C11 - C01 * C01
		if abs(det) < 1e-9:
			break
		al1 = (X0 * C11 - X1 * C01) / det
		al2 = (C00 * X1 - C01 * X0) / det
		if al1 <= 0 or al2 <= 0 or al1 > 2.5 * chord or al2 > 2.5 * chord:
			break
		C = (p0, (p0[0] + t1[0] * al1, p0[1] + t1[1] * al1),
			(p3[0] + t2[0] * al2, p3[1] + t2[1] * al2), p3)
		err = 0.0
		for pt, u in zip(samples, us):
			Q = _bez(C, u)
			err = max(err, math.hypot(pt[0] - Q[0], pt[1] - Q[1]))
		if best is None or err < best[0]:
			best = (err, C)
		# Newton step on the parameters
		new = []
		for pt, u in zip(samples, us):
			Q = _bez(C, u)
			D = _bezD(C, u)
			mt = 1 - u
			DD = (6 * (mt * (C[2][0] - 2 * C[1][0] + C[0][0]) + u * (C[3][0] - 2 * C[2][0] + C[1][0])),
				6 * (mt * (C[2][1] - 2 * C[1][1] + C[0][1]) + u * (C[3][1] - 2 * C[2][1] + C[1][1])))
			num = (Q[0] - pt[0]) * D[0] + (Q[1] - pt[1]) * D[1]
			den = D[0] * D[0] + D[1] * D[1] + (Q[0] - pt[0]) * DD[0] + (Q[1] - pt[1]) * DD[1]
			new.append(min(1.0, max(0.0, u - num / den)) if abs(den) > 1e-12 else u)
		new[0], new[-1] = 0.0, 1.0
		us = new
	return best[1] if best else None



def _outline_points(points,types,tolerance=.02):
    on=[i for i,t in enumerate(types) if t!='offcurve']
    if not on:return []
    result=[points[on[0]]]
    def distance(p,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1];ll=dx*dx+dy*dy
        t=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/ll)) if ll else 0.
        return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
    def flatten(c,depth=0):
        if depth>=14 or max(distance(c[1],c[0],c[3]),distance(c[2],c[0],c[3]))<=tolerance:
            result.append(c[3]);return
        a,b,c1,d=c
        mid=lambda a,b:((a[0]+b[0])/2.,(a[1]+b[1])/2.)
        ab,bc,cd=mid(a,b),mid(b,c1),mid(c1,d)
        abc,bcd=mid(ab,bc),mid(bc,cd);m=mid(abc,bcd)
        flatten((a,ab,abc,m),depth+1);flatten((m,bcd,cd,d),depth+1)
    for a,b in zip(on,on[1:]+on[:1]):
        between=[];j=(a+1)%len(points)
        while j!=b:between.append(j);j=(j+1)%len(points)
        if len(between)==2:flatten([points[i] for i in (a,*between,b)])
        else:result.append(points[b])
    return result[:-1]

def _outline_crossings(polygons):
    edges=[]
    for k,poly in enumerate(polygons):
        for i,a in enumerate(poly):
            b=poly[(i+1)%len(poly)]
            if math.dist(a,b)<1e-10:continue
            edges.append((min(a[0],b[0]),max(a[0],b[0]),min(a[1],b[1]),max(a[1],b[1]),k,i,a,b,len(poly)))
    edges.sort(key=lambda e:e[0]);active=[];count=0
    cross=lambda a,b:a[0]*b[1]-a[1]*b[0]
    for e in edges:
        active=[p for p in active if p[1]>=e[0]]
        for p in active:
            if p[2]>e[3] or p[3]<e[2]:continue
            if p[4]==e[4] and ((p[5]-e[5])%e[8] in (0,1,e[8]-1)):continue
            a,b,c,d=p[6],p[7],e[6],e[7]
            v=(b[0]-a[0],b[1]-a[1]);w=(d[0]-c[0],d[1]-c[1]);r=(c[0]-a[0],c[1]-a[1]);den=cross(v,w)
            if abs(den)>1e-10:
                t,u=cross(r,w)/den,cross(r,v)/den
                if 1e-8<t<1-1e-8 and 1e-8<u<1-1e-8:count+=1
        active.append(e)
    return count

def _outline_signature(polygons):
    signs=[]
    for poly in polygons:
        area=sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(poly,poly[1:]+poly[:1]))
        signs.append(0 if abs(area)<1e-8 else (1 if area>0 else -1))
    def inside(p,poly):
        result=False
        for a,b in zip(poly,poly[1:]+poly[:1]):
            if (a[1]>p[1])!=(b[1]>p[1]) and p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:result=not result
        return result
    nesting=tuple(inside(a[0],b) for i,a in enumerate(polygons) if a for j,b in enumerate(polygons) if b and i!=j)
    return tuple(signs),nesting

def _smooth_points(points,original,types,smooth):
    out=list(points);n=len(out)
    unit=lambda x,y:(x/math.hypot(x,y),y/math.hypot(x,y)) if math.hypot(x,y)>1e-10 else None
    for i in range(n):
        if types[i]=='offcurve' or not smooth[i] or types[(i-1)%n]!='offcurve' or types[(i+1)%n]!='offcurve':continue
        a,b,c=original[(i-1)%n],original[i],original[(i+1)%n]
        ta,tb=unit(b[0]-a[0],b[1]-a[1]),unit(c[0]-b[0],c[1]-b[1])
        if not ta or not tb or math.dist(ta,tb)>.05:continue
        a,b,c=out[(i-1)%n],out[i],out[(i+1)%n]
        u,v=unit(b[0]-a[0],b[1]-a[1]),unit(c[0]-b[0],c[1]-b[1])
        if not u or not v:continue
        if u[0]*v[0]+u[1]*v[1]<=0:return None
        if math.dist(u,v)<1e-9:continue
        t=unit(u[0]+v[0],u[1]+v[1]);la,lb=math.dist(a,b),math.dist(b,c)
        out[(i-1)%n]=(b[0]-la*t[0],b[1]-la*t[1]);out[(i+1)%n]=(b[0]+lb*t[0],b[1]+lb*t[1])
    return out

def _safe_contours(original,candidate,types,smooth):
    """Reduce only the correction if it would change contour topology.

    `original` is already slanted. The requested angle is never reduced.
    """
    polygons=[_outline_points(p,t) for p,t in zip(original,types)]
    original_count=_outline_crossings(polygons);signature=_outline_signature(polygons)
    def attempt(amount):
        result=[]
        for before,after,t,s in zip(original,candidate,types,smooth):
            pts=[(a[0]+amount*(b[0]-a[0]),a[1]+amount*(b[1]-a[1])) for a,b in zip(before,after)]
            if any(not math.isfinite(v) for p in pts for v in p):return None
            pts=_smooth_points(pts,before,t,s)
            if pts is None:return None
            result.append(pts)
        poly=[_outline_points(p,t) for p,t in zip(result,types)]
        if _outline_crossings(poly)>original_count:return None
        if _outline_signature(poly)!=signature:return None
        return result
    full=attempt(1.)
    if full is not None:return full,1.
    upper=1.
    for step in range(7,-1,-1):
        lower=step/8.;result=attempt(lower)
        if result is None:upper=lower;continue
        for _ in range(7):
            mid=(lower+upper)/2.;trial=attempt(mid)
            if trial is None:upper=mid
            else:lower=mid;result=trial
        return attempt(lower*.98) or original,lower*.98
    return original,0.


def _correctRuns(path, strength, angle, stem, origin, terminal_weights, clip_to_line):
    """Correct connected cubic runs, then reconcile their shared endpoints."""
    nodes=list(path.nodes); n=len(nodes)
    xy=[(a.position.x,a.position.y) for a in nodes]
    on=[i for i,a in enumerate(nodes) if a.type!='offcurve']
    sub,roots,unit,ray=_sub,_extremeParams,_unit,_rayInt
    frags=[]
    for k,a in enumerate(on):
        b=on[(k+1)%len(on)];ids=[];j=(a+1)%n
        while j!=b:ids.append(j);j=(j+1)%n
        if len(ids)!=2:
            frags.append(dict(C=[xy[a],xy[b]],a=a,b=b,orig=None,ts=(0,1)))
            continue
        C=[xy[a],xy[ids[0]],xy[ids[1]],xy[b]]
        frags.append(dict(C=C,a=a,b=b,orig=(a,*ids,b),ts=(0,1)))
    def tangent(f,start):
        pts=f['C'] if start else list(reversed(f['C']))
        for p in pts[1:]:
            t=unit(p[0]-pts[0][0],p[1]-pts[0][1])
            if t:return t if start else (-t[0],-t[1])
    def pivot(i):
        f=frags[i];prev=frags[i-1]
        if len(f['C'])==2 or len(prev['C'])==2 or not isinstance(f['a'],int):return True
        a,b=tangent(prev,False),tangent(f,True)
        if not a or not b:return True
        if math.dist(a,b)>.05:return True
        return min(abs(C[a][j]-C[b][j]) for C,a,b in [(f['C'],1,0),(prev['C'],-2,-1)] for j in (0,1))<.02
    def extension(C,start,whole):
        roots0=sorted(t for t in roots(C) if .001<t<.999)
        if roots0:
            t=roots0[0] if start else roots0[-1];internal=True
        else:
            ts=roots(C)+_inflections(C)
            ts=[t for t in ts if (-3<=t< -1e-6 if start else 1+1e-6<t<=4)]
            deriv=_bezD(C,0 if start else 1)
            if min(abs(v) for v in deriv)<1e-6:return None
            t=(max(ts) if start else min(ts)) if ts else (-3. if start else 4.);internal=False
        E=list(sub(C,t,0)) if start else list(sub(C,1,t))
        # At an internal extreme the continuation is traversed backwards.
        far=E[0] if start else E[-1];at=C[0] if start else C[-1]
        at=whole[-1] if start else whole[0]
        handle=whole[-2] if start else whole[1]
        ta=(handle[0]-at[0],handle[1]-at[1]);tf=_bezD(C,t)
        ua,uf=unit(*ta),unit(*tf)
        if not ua or not uf or abs(ua[0]*uf[1]-ua[1]*uf[0])<.001:return None
        hit=ray(at,ta,far,tf)
        if not hit:return None
        center=hit[0]
        size=max(1,max(p[0] for p in whole)-min(p[0] for p in whole),max(p[1] for p in whole)-min(p[1] for p in whole))
        if math.dist(center,far)>4*size:return None
        mirror=(2*far[0]-center[0],2*far[1]-center[1])
        return dict(P=E,center=center,mirror=mirror,internal=internal,t=t)
    def smooth_at(index):
        prev=frags[index-1];nxt=frags[index]
        t0,t1=tangent(prev,False),tangent(nxt,True)
        return t0 and t1 and math.dist(t0,t1)<=.05
    starts=[i for i in range(len(frags)) if pivot(i)]
    if not starts:return
    pivots=[]
    for i,f in enumerate(frags):
        if i in starts:
            prev=frags[i-1]
            pivots.append(dict(order=float(i),point=f['C'][0],incoming=prev['C'][-2],outgoing=f['C'][1],real=i,both=len(prev['C'])==4 and len(f['C'])==4,ovbefore=False,ovafter=False))
        if len(f['C'])==4:
            for t in sorted(set(roots(f['C']))):
                if .001<t<.999:
                    left,right=sub(f['C'],0,t),sub(f['C'],t,1)
                    pivots.append(dict(order=i+t,point=left[-1],incoming=left[-2],outgoing=right[1],real=None,both=True,ovbefore=False,ovafter=False))
    pivots.sort(key=lambda p:p['order'])
    for i,p in enumerate(pivots):
        q=pivots[(i+1)%len(pivots)]
        def qualified(p,key):
            tol=1e-9 if p['real'] is not None else 1.
            return not p['both'] or min(abs(p['point'][j]-p[key][j]) for j in (0,1))<tol
        center=None
        if qualified(p,'outgoing') and qualified(q,'incoming'):
            va=(p['outgoing'][0]-p['point'][0],p['outgoing'][1]-p['point'][1]);vb=(q['incoming'][0]-q['point'][0],q['incoming'][1]-q['point'][1])
            hit=ray(p['point'],va,q['point'],vb)
            if hit:center=hit[0]
        p['after']=center;q['before']=center
    real={p['real']:p for p in pivots if p['real'] is not None}
    for i,p in real.items():
        for forward,key in [(True,'after'),(False,'before')]:
            C=frags[i if forward else i-1]['C']
            if len(C)!=4:continue
            ts=sorted(t for t in _inflections(C) if .001<t<.999)
            if not ts:continue
            t=ts[0] if forward else ts[-1]
            part=sub(C,0,t) if forward else sub(C,t,1)
            endpoint,handle=(part[0],part[1]) if forward else (part[-1],part[-2])
            p[key]=(endpoint[0]+3*(handle[0]-endpoint[0]),endpoint[1]+3*(handle[1]-endpoint[1]))
            p['ov'+key]=True
    def curvature_sign(C,at_start=True):
        if not at_start:C=list(reversed(C))
        a=(C[1][0]-C[0][0],C[1][1]-C[0][1]);b=(C[2][0]-C[1][0],C[2][1]-C[1][1])
        x=a[0]*b[1]-a[1]*b[0]
        return 0 if abs(x)<1e-9 else 1 if x>0 else -1
    def inflection_time(C):
        def cross(t):
            v=_bezD(C,t)
            a=[C[2][j]-2*C[1][j]+C[0][j] for j in (0,1)]
            b=[C[3][j]-2*C[2][j]+C[1][j] for j in (0,1)]
            w=[6*((1-t)*a[j]+t*b[j]) for j in (0,1)]
            return v[0]*w[1]-v[1]*w[0]
        lo=0.;prev=cross(lo)
        for k in range(1,65):
            hi=k/64.;val=cross(hi)
            if prev*val<=0:
                for _ in range(50):
                    mid=(lo+hi)/2.;v=cross(mid)
                    if abs(v)<1e-8:break
                    if cross(lo)*v>0:lo=mid
                    else:hi=mid
                    if hi-lo<1e-8:mid=(lo+hi)/2.;break
                return mid if .001<mid<.999 else None
            lo=hi;prev=val
        return None
    for i,p in real.items():
        for forward,key in [(True,'after'),(False,'before')]:
            if p['ov'+key]:continue
            idx=i if forward else (i-1)%len(frags);last_sign=0
            for step in range(32):
                C=frags[idx]['C']
                if len(C)!=4:break
                C=C if forward else list(reversed(C))
                sign=curvature_sign(C)
                if step and ((sign and last_sign and sign!=last_sign) or inflection_time(C) is not None):
                    q=p['point'];h=p['outgoing' if forward else 'incoming']
                    p[key]=(q[0]+3*(h[0]-q[0]),q[1]+3*(h[1]-q[1]));p['ov'+key]=True
                    break
                last_sign=-curvature_sign(C,False) or sign or last_sign
                nxt=(idx+1)%len(frags) if forward else idx
                if nxt in real or nxt==i:break
                idx=(idx+(1 if forward else -1))%len(frags)
    # A geometric corner with two curves supplies its own adjacent centers.
    for i,p in real.items():
        if not p['both'] or smooth_at(i):continue
        for forward,key in [(True,'after'),(False,'before')]:
            if p['ov'+key]:continue
            C=frags[i if forward else i-1]['C']
            va=(C[1][0]-C[0][0],C[1][1]-C[0][1])
            vb=(C[-2][0]-C[-1][0],C[-2][1]-C[-1][1])
            hit=ray(C[0],va,C[-1],vb)
            if hit:p[key]=hit[0]
    runs=[]
    for k,i in enumerate(starts):
        stop=starts[(k+1)%len(starts)];fs=[frags[i]];j=(i+1)%len(frags)
        while j!=stop:fs.append(frags[j]);j=(j+1)%len(frags)
        points=list(fs[0]['C'])
        for f in fs[1:]:points.extend(f['C'][1:])
        a,b=tangent(fs[0],True),tangent(fs[-1],False)
        av=(points[1][0]-points[0][0],points[1][1]-points[0][1])
        bv=(points[-2][0]-points[-1][0],points[-2][1]-points[-1][1])
        hit=ray(points[0],av,points[-1],bv)
        corner=hit[0] if hit else ((points[0][0]+points[-1][0])/2.,(points[0][1]+points[-1][1])/2.)

        C=[points[0],points[1],points[-2],points[-1]]
        dx,dy=_bezD(C,.5);d=1 if dx*dy>1e-9 else (-1 if dx*dy< -1e-9 else 0)
        ea=extension(fs[0]['C'],True,points) if len(fs[0]['C'])==4 and not smooth_at(i) else None
        eb=extension(fs[-1]['C'],False,points) if len(fs[-1]['C'])==4 and not smooth_at(stop) else None
        selected=eb['center'] if eb else ea['center'] if ea else corner
        runs.append(dict(fs=fs,P=points,corner=selected,d=d,curve=len(fs[0]['C'])>2,ea=ea,eb=eb,start=real[i],end=real[stop]))
    proposals={};newfrags=[]
    def moved(P,S,E,amount):
        vx,vy=E[0]-S[0],E[1]-S[1];ll=vx*vx+vy*vy
        if ll<1e-8:return P
        t=max(0,min(1,((P[0]-S[0])*vx+(P[1]-S[1])*vy)/ll))
        w=max(-1.,min(1.,amount))*min(t,1-t)
        return P[0]+w*vx,P[1]+w*vy
    def correct_half(P,S,E,amount):
        theta=math.radians(angle)
        comp=1./math.cos(theta*stem)
        def sc(p):return (origin[0]+comp*(p[0]-origin[0]),p[1])
        points=[sc(p) for p in [S]+P+[E]]
        return [moved(p,points[0],points[-1],amount) for p in points[1:-1]]
    for k,r in enumerate(runs):
        P=r['P'];C=r['corner'];before=runs[k-1];after=runs[(k+1)%len(runs)]
        weight=min((terminal_weights or {}).get(f['a'],1.) for f in r['fs'])
        if not r['curve']:
            pp=P[:]
        else:
            ea,eb=r['ea'],r['eb']
            CA=ea['center'] if ea else r['start']['after'] if r['start']['ovafter'] else C
            CB=eb['center'] if eb else r['end']['before'] if r['end']['ovbefore'] else C
            A=ea['mirror'] if ea else r['start']['before'] or (2*P[0][0]-C[0],2*P[0][1]-C[1])
            B=eb['mirror'] if eb else r['end']['after'] or (2*P[-1][0]-C[0],2*P[-1][1]-C[1])
            padA=ea['P'][:-1] if ea and not ea['internal'] else []
            padB=eb['P'][1:] if eb and not eb['internal'] else []
            Padded=padA+P+padB
            dx,dy=_bezD([Padded[0],Padded[1],Padded[-2],Padded[-1]],.5)
            dr=1 if dx*dy>1e-9 else (-1 if dx*dy< -1e-9 else 0)
            d2=after['d'] if after['curve'] else -dr
            pp=correct_half(Padded[:-2],A,CA,strength*dr*weight)+Padded[-2:]
            pp=pp[:2]+correct_half(pp[2:],CB,B,strength*d2*weight)
            pp=pp[len(padA):len(padA)+len(P)]
        z=0
        for f in r['fs']:
            count=len(f['C']);newfrags.append((f,pp[z:z+count]));z+=count-1
        for key,point in [(r['fs'][0]['a'],pp[0]),(r['fs'][-1]['b'],pp[-1])]:proposals.setdefault(key,[]).append(point)
    # Reconcile complete cubic pieces at their common junction.

    def extension_keeps_direction(C,t,start):
        if 0<=t<=1:return True
        end=C[0] if start else C[-1]
        near=C[1:] if start else list(reversed(C[:-1]))
        tangent=next(((q[0]-end[0],q[1]-end[1]) for q in near if math.dist(q,end)>1e-9),None)
        if tangent is None:return False
        if not start:tangent=(-tangent[0],-tangent[1])
        z=[q[0]*tangent[0]+q[1]*tangent[1] for q in C]
        a=-z[0]+3*z[1]-3*z[2]+z[3];b=2*(z[0]-2*z[1]+z[2]);c=z[1]-z[0]
        rs=[]
        if abs(a)<1e-10:
            if abs(b)>1e-10:rs=[-c/b]
        else:
            disc=b*b-4*a*c
            if disc>=0:rs=[(-b-math.sqrt(disc))/(2*a),(-b+math.sqrt(disc))/(2*a)]
        lo,hi=(t,0.) if start else (1.,t)
        return not any(lo+1e-8<r<hi-1e-8 for r in rs)

    def sampled_corner(C,D,pivot,bez,samples=200,tolerance=.5):
        # Locate candidate crossings, then solve on the actual cubic curves.
        ta=[4.*i/samples for i in range(samples+1)]
        tb=[-1.+4.*i/samples for i in range(samples+1)]
        pa=[bez(C,t) for t in ta];pb=[bez(D,t) for t in tb]
        def cross(a,b):return a[0]*b[1]-a[1]*b[0]
        def delta(a,b):return (a[0]-b[0],a[1]-b[1])
        def distance(P,Q,V):
            ll=V[0]*V[0]+V[1]*V[1]
            t=max(0.,min(1.,((P[0]-Q[0])*V[0]+(P[1]-Q[1])*V[1])/ll)) if ll>1e-9 else 0.
            return math.hypot(Q[0]+t*V[0]-P[0],Q[1]+t*V[1]-P[1])
        boxes=[]
        for j in range(samples):
            a,b=pb[j],pb[j+1]
            boxes.append((min(a[0],b[0]),max(a[0],b[0]),min(a[1],b[1]),max(a[1],b[1])))
        candidates=[]
        for i in range(samples):
            a,b=pa[i],pa[i+1];v=delta(b,a)
            xmin,xmax=min(a[0],b[0])-tolerance,max(a[0],b[0])+tolerance
            ymin,ymax=min(a[1],b[1])-tolerance,max(a[1],b[1])+tolerance
            for j,box in enumerate(boxes):
                if box[0]>xmax or box[1]<xmin or box[2]>ymax or box[3]<ymin:continue
                q,r=pb[j],pb[j+1];w=delta(r,q);d=delta(q,a);den=cross(v,w)
                hit=False
                if abs(den)>1e-9:
                    x,y=cross(d,w)/den,cross(d,v)/den
                    if 0<=x<=1 and 0<=y<=1:
                        candidates.append((ta[i]+x*(ta[i+1]-ta[i]),tb[j]+y*(tb[j+1]-tb[j])))
                        hit=True
                if not hit and min(distance(a,q,w),distance(b,q,w),distance(q,a,v),distance(r,a,v))<=tolerance:
                    candidates.append(((ta[i]+ta[i+1])/2.,(tb[j]+tb[j+1])/2.))
        refined=[]
        for t,u in candidates:
            for _ in range(12):
                pc,pd=bez(C,t),bez(D,u);dx,dy=pc[0]-pd[0],pc[1]-pd[1]
                if math.hypot(dx,dy)<1e-8:break
                dc,dd=_bezD(C,t),_bezD(D,u)
                den=cross(dc,dd)
                if abs(den)<1e-12:break
                dt=(dy*dd[0]-dx*dd[1])/den
                du=(dc[0]*dy-dc[1]*dx)/den
                step=max(1.,abs(dt)/.05,abs(du)/.05)
                t+=dt/step;u+=du/step
                if not 0<=t<=4 or not -1<=u<=3:break
            # A trim must retain its original far endpoint and traversal order.
            if not 1e-8<t<=4 or not -1<=u<1-1e-8:continue
            pc,pd=bez(C,t),bez(D,u)
            if math.dist(pc,pd)>.5:continue
            if not extension_keeps_direction(C,t,False) or not extension_keeps_direction(D,u,True):continue
            refined.append((math.dist(pc,pivot),t,u))
        if not refined:return None
        return min(refined)[1:]

    for i,(f,C) in enumerate(newfrags):
        prev,D=newfrags[i-1]
        index=frags.index(f)
        if len(C)==4 and len(D)==2 and not smooth_at(index):
            if math.dist(f['C'][0],f['C'][1])<1e-9:
                D[-1]=C[0];continue
            u=clip_to_line(C,0,D[0],D[-1])
            if u is not None and -1<u<.999:
                C[:]=sub(C,u,1);D[-1]=C[0];continue
        if len(C)==2 and len(D)==4 and not smooth_at(index):
            if math.dist(prev['C'][-1],prev['C'][-2])<1e-9:
                C[0]=D[-1];continue
            t=clip_to_line(D,1,C[0],C[-1])
            if t is not None and .001<t<2:
                D[:]=sub(D,0,t);C[0]=D[-1];continue
        if len(C)==4 and len(D)==4 and not smooth_at(index):
            hit=sampled_corner(D,C,xy[f['a']],_bez)
            if hit:
                t,u=hit;D[:]=sub(D,0,t);C[:]=sub(C,u,1)
                continue
        # Preserve a smooth axis join when only one span retains its tangent.
        if len(C)==4 and len(D)==4 and smooth_at(index):
            original=tangent(f,True)
            incoming=unit(D[-1][0]-D[-2][0],D[-1][1]-D[-2][1])
            outgoing=unit(C[1][0]-C[0][0],C[1][1]-C[0][1])
            if original and incoming and outgoing:
                ai=abs(incoming[0]*original[1]-incoming[1]*original[0])
                ao=abs(outgoing[0]*original[1]-outgoing[1]*original[0])
                if min(abs(v) for v in original)<1e-9 and min(ai,ao)<1e-6 and max(ai,ao)>.01:
                    q=D[-1] if ai<ao else C[0]
                    li=max(0,(q[0]-D[-2][0])*original[0]+(q[1]-D[-2][1])*original[1])
                    lo=max(0,(C[1][0]-q[0])*original[0]+(C[1][1]-q[1])*original[1])
                    D[-1]=q;C[0]=q
                    D[-2]=(q[0]-li*original[0],q[1]-li*original[1])
                    C[1]=(q[0]+lo*original[0],q[1]+lo*original[1])
                    continue
        # Preserve the node position supplied by the adjoining valid span.
        if f['a'] in proposals:
            q=C[0]
            if len(C)==4 and len(D)==4:
                pvt=real.get(index)
                if pvt and pvt['after'] is None and pvt['before'] is not None:q=D[-1]
            da=(q[0]-D[-1][0],q[1]-D[-1][1]);db=(q[0]-C[0][0],q[1]-C[0][1])
            D[-1]=q;C[0]=q
            if len(D)==4:D[-2]=(D[-2][0]+da[0],D[-2][1]+da[1])
            if len(C)==4:C[1]=(C[1][0]+db[0],C[1][1]+db[1])
    collected={}
    for f,p in newfrags:
        if f['orig'] is None:
            for idx,key in [(0,'a'),(-1,'b')]:
                if isinstance(f[key],int):nodes[f[key]].position=NSMakePoint(*p[idx])
        else:collected.setdefault(f['orig'],[]).append((f['ts'],p))
    for ids,parts in collected.items():
        for i,p in zip(ids,parts[0][1]):nodes[i].position=NSMakePoint(*p)

    # An exactly horizontal edge is a cap/baseline constraint, including
    # edges encoded as cubics. Curve intersections must not lift its corner.
    locked={}
    for f in frags:
        if max(p[1] for p in f['C'])-min(p[1] for p in f['C'])<1e-9:
            ids=f['orig'] if f['orig'] is not None else (f['a'],f['b'])
            for index in ids:locked[index]=xy[index][1]
    for index,y in locked.items():
        node=nodes[index];dy=y-node.position.y
        node.position=NSMakePoint(node.position.x,y)
        if node.type!='offcurve' and node.smooth:
            for j in ((index-1)%n,(index+1)%n):
                if j not in locked and nodes[j].type=='offcurve':
                    h=nodes[j];h.position=NSMakePoint(h.position.x,h.position.y+dy)

    # Avoid floating-point drift at unchanged coordinates.
    for nd,old in zip(nodes,xy):
        x,y=nd.position.x,nd.position.y
        if abs(x-old[0])<1e-10:x=old[0]
        if abs(y-old[1])<1e-10:y=old[1]
        nd.position=NSMakePoint(x,y)

def _bowl_regions(points, types):
    """Find white cavities bounded by ink on three or four sides.

    Scan both axes so openings may face up, down, left or right. Ambiguous
    branching cavities and narrow slits are excluded. Regions include the
    adjacent ink, letting a single deformation move both sides of a stroke.
    """
    polygons = [_outline_points(p, t, .5) for p, t in zip(points, types)]
    if not polygons or _outline_crossings(polygons):
        return []
    regions = []
    for axis in (0, 1):
        polys = [[(p[axis], p[1-axis]) for p in poly] for poly in polygons]
        lo = min(p[1] for poly in polys for p in poly)
        hi = max(p[1] for poly in polys for p in poly)
        step = (hi-lo)/96.
        if step < 1e-6:
            continue
        def cuts(y):
            xs = []
            for poly in polys:
                for a,b in zip(poly, poly[1:]+poly[:1]):
                    if (a[1]>y)!=(b[1]>y):
                        xs.append(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
            return sorted(xs)
        def ink(x,y):
            return sum(v<x for v in cuts(y))%2 == 1
        tracks=[]; active=[]
        for row in range(96):
            y=lo+(row+.5)*step; xs=cuts(y); current=[]
            for j in range(1,len(xs)-2,2):
                a,b=xs[j],xs[j+1]
                if b-a < step*2: continue
                matches=[t for t in active if min(b,t[-1][2])-max(a,t[-1][1]) > .5*min(b-a,t[-1][2]-t[-1][1])]
                # A split/merge is ambiguous: don't join it into a single bowl.
                if len(matches)==1 and matches[0] not in current:
                    t=matches[0]
                else:
                    t=[];tracks.append(t)
                t.append((y,a,b,xs[j-1],xs[j+2]));current.append(t)
            active=current
        for t in tracks:
            if len(t)<10: continue
            y1,y2=t[0][0]-step/2,t[-1][0]+step/2
            a=min(r[1] for r in t);b=max(r[2] for r in t)
            if min(b-a,y2-y1) < .12*max(b-a,y2-y1): continue
            cx=(a+b)/2
            # A white channel between separate stems is not a bowl.
            if not (ink(cx,y1-step) or ink(cx,y2+step)): continue
            left=min(r[3] for r in t);right=max(r[4] for r in t)
            wall=min(a-left,right-b)
            if wall<=step: continue
            box=(a,y1-step,b,y2+step)
            if axis: box=(box[1],box[0],box[3],box[2])
            # Prefer one coherent region over competing overlapping cavities.
            if any(min(box[2],q[2])-max(box[0],q[0]) > .25*min(box[2]-box[0],q[2]-q[0]) and min(box[3],q[3])-max(box[1],q[1]) > .25*min(box[3]-box[1],q[3]-q[1]) for q in regions): continue
            regions.append(box)
    return regions


def _upright_bowls(original, corrected, types, smooth, angle, y0, amount):
    if amount<=0: return corrected
    regions=_bowl_regions(original,types)
    if not regions:return corrected
    k=math.tan(math.radians(angle))
    fitted=[]
    for l,b,r,t in regions:
        samples=[(a[1],z[0]-a[0]) for src,dst,ts in zip(original,corrected,types) for a,z,kind in zip(src,dst,ts) if kind!='offcurve' and l-1<=a[0]<=r+1 and b-1<=a[1]<=t+1]
        if len(samples)<4:continue
        mean_y=sum(y for y,d in samples)/len(samples)
        mean_d=sum(d for y,d in samples)/len(samples)
        variance=sum((y-mean_y)**2 for y,d in samples)
        if variance<1e-8:continue
        slope=sum((y-mean_y)*(d-mean_d) for y,d in samples)/variance
        # Existing curve correction may already restore a round bowl's axis.
        # Remove the measured residual lean, never apply a second unshear.
        if abs(slope)>abs(k)*1.5:continue
        fitted.append((l,b,r,t,slope))
    def ramp(v,lo,hi,fade):
        d=max(lo-v,0.,v-hi)/fade
        return 1. if d<=0 else (0. if d>=1 else 1.-d*d*(3.-2.*d))
    def shift(x,y):
        # Evaluate in unslanted coordinates; the correction already computed
        # by Curse remains part of the outline at every slider value.
        x=x-(y-y0)*k
        total=weight=0.
        contributions=[]
        for l,b,r,t,slope in fitted:
            fade=max(r-l,t-b)*.5
            w=ramp(x,l,r,fade)*ramp(y,b,t,fade)
            contributions.append((w,slope*(y-(b+t)/2.)))
        full=[d for w,d in contributions if w>=1.-1e-10]
        if full:return -amount*sum(full)/len(full)
        for w,d in contributions:
            influence=w/max(1e-10,1.-w)
            total+=influence*d;weight+=influence
        return -amount*total/max(1.,weight)
    candidate=[]
    for pts,ts in zip(corrected,types):
        result=[];n=len(pts)
        for i,(x,y) in enumerate(pts):
            if ts[i]!='offcurve':
                result.append((x+shift(x,y),y));continue
            # Transport handles with the same local derivative at their
            # on-curve node, preserving incoming/outgoing tangent alignment.
            j=(i-1)%n if ts[(i-1)%n]!='offcurve' else (i+1)%n
            if ts[j]=='offcurve':return corrected
            ax,ay=pts[j];eps=.01
            dx=(shift(ax+eps,ay)-shift(ax-eps,ay))/(2*eps)
            dy=(shift(ax,ay+eps)-shift(ax,ay-eps))/(2*eps)
            result.append((x+shift(ax,ay)+dx*(x-ax)+dy*(y-ay),y))
        candidate.append(result)
    safe,_=_safe_contours(corrected,candidate,types,smooth)
    return safe


class MakeItalic(FilterWithDialog):

	# ------------------------------------------------------------ UI

	@objc.python_method
	def settings(self):
		self.menuName = "Curse"
		self.actionButtonLabel = "Apply"
		self._angle = 12.0
		self._fields = {}
		self._values = {'curve': 100., 'terminals': 0., 'diagonal': 100., 'stem': 0.}
		W = 340
		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 400))

		def label(text, x, y, w, parent=view, size=12):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, 20))
			f.setStringValue_(text)
			f.setBezeled_(False)
			f.setDrawsBackground_(False)
			f.setEditable_(False)
			f.setSelectable_(False)
			f.setFont_(NSFont.systemFontOfSize_(size))
			parent.addSubview_(f)
			return f

		def field(value, x, y, parent=view):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, 62, 22))
			f.setStringValue_(value)
			f.setAlignment_(1)
			f.setTarget_(self)
			f.setAction_("fieldChanged:")
			f.setDelegate_(self)
			parent.addSubview_(f)
			return f

		self._mainView = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 400))
		view.addSubview_(self._mainView)
		label("Angle", 16, 361, 160, self._mainView)
		self.angleField = field("12°", 262, 360, self._mainView)
		self.angleField.setToolTip_("Degrees to add. Negative values lean left.")
		label("Balance", 16, 329, 160, self._mainView)
		self.balanceField = field("100%", 262, 304, self._mainView)
		self.balanceSlider = NSSlider.alloc().initWithFrame_(NSMakeRect(16, 304, 232, 22))
		self.balanceSlider.setMinValue_(0)
		self.balanceSlider.setMaxValue_(100)
		self.balanceSlider.setDoubleValue_(100)
		self.balanceSlider.setContinuous_(False)
		self.balanceSlider.setTarget_(self)
		self.balanceSlider.setAction_("balanceChanged:")
		self.balanceSlider.setToolTip_("Blend from a plain slant to the corrected outline.")
		self._mainView.addSubview_(self.balanceSlider)
		label("Upright bowls", 16, 267, 200, self._mainView)
		self.uprightField = field("0%", 262, 242, self._mainView)
		self.uprightSlider = NSSlider.alloc().initWithFrame_(NSMakeRect(16, 242, 232, 22))
		self.uprightSlider.setMinValue_(0)
		self.uprightSlider.setMaxValue_(100)
		self.uprightSlider.setDoubleValue_(0)
		self.uprightSlider.setContinuous_(False)
		self.uprightSlider.setTarget_(self)
		self.uprightSlider.setAction_("balanceChanged:")
		self.uprightSlider.setToolTip_("Keep detected bowls and their surrounding strokes upright. Ambiguous shapes are skipped. Balance scales the effect.")
		self._mainView.addSubview_(self.uprightSlider)
		self.status = label("Preview the selected outlines, then Apply.", 16, 10, 310, self._mainView, 11)

		self._detailView = NSView.alloc().initWithFrame_(NSMakeRect(0, 45, W, 142))
		for key, title, x, y in [('curve', 'Rounds', 16, 106), ('diagonal', 'Diagonals', 178, 106),
				('stem', 'Stem weight', 16, 66), ('terminals', 'Endings', 178, 66)]:
			label(title, x, y + 18, 140, self._detailView, 11)
			self._fields[key] = field("%g%%" % self._values[key], x, y - 4, self._detailView)
		self._fields['curve'].setToolTip_("Curve rebalance before slanting, 0–150%.")
		self._fields['diagonal'].setToolTip_("Restore perpendicular width of straight diagonals, 0–150%.")
		self._fields['stem'].setToolTip_("Restore perpendicular width of straight vertical stems, 0–150%.")
		self._fields['terminals'].setToolTip_("Reduce curve adjustment at detected stroke endings, 0–100%.")
		self.vertCheck = NSButton.alloc().initWithFrame_(NSMakeRect(12, 18, 310, 24))
		self.vertCheck.setButtonType_(3)
		self.vertCheck.setTitle_("Refit extrema")
		self.vertCheck.setState_(0)
		self.vertCheck.setToolTip_("Move eligible nodes back to vertical extrema within a small shape tolerance.")
		self.vertCheck.setTarget_(self)
		self.vertCheck.setAction_("balanceChanged:")
		self._detailView.addSubview_(self.vertCheck)
		view.addSubview_(self._detailView)
		self.dialog = view

	@objc.python_method
	def start(self):
		try:
			ia = float(Glyphs.font.selectedFontMaster.italicAngle)
			if math.isfinite(ia) and 0 < abs(ia) <= 35:
				self._angle = ia
				self.angleField.setStringValue_("%g°" % ia)
		except Exception:
			pass

	@objc.python_method
	def val(self, key):
		v = self._values[key]
		return v if key == 'terminals' else v * self.balanceSlider.doubleValue() / 100.

	def balanceChanged_(self, sender):
		self.balanceField.setStringValue_("%g%%" % round(self.balanceSlider.doubleValue()))
		self.uprightField.setStringValue_("%g%%" % round(self.uprightSlider.doubleValue()))
		self.update()

	def control_textView_doCommandBySelector_(self, control, textView, command):
		commands = {'moveUp:': 1, 'moveDown:': -1,
			'moveUpAndModifySelection:': 1, 'moveDownAndModifySelection:': -1}
		command = str(command)
		if command not in commands:
			return False
		fields = [self.angleField, self.balanceField, self.uprightField] + list(self._fields.values())
		if control not in fields:
			return False
		try:
			value = float(textView.string().replace('°', '').replace('%', '').strip())
			if not math.isfinite(value):
				return False
		except (ValueError, TypeError):
			return False
		shift = 'AndModifySelection' in command or bool(NSEvent.modifierFlags() & (1 << 17))
		control.setStringValue_(str(value + commands[command] * (10 if shift else 1)))
		self.fieldChanged_(control)
		# Keep the active field editor in sync with clamped/formatted values.
		textView.setString_(control.stringValue())
		textView.setSelectedRange_((0, len(control.stringValue())))
		return True

	def controlTextDidEndEditing_(self, notification):
		self.fieldChanged_(notification.object())

	def fieldChanged_(self, sender):
		try:
			v = float(sender.stringValue().replace("°", "").replace("%", "").strip())
			if not math.isfinite(v):
				raise ValueError("Enter a finite number")
			if sender == self.angleField:
				self._angle = max(-35., min(35., v))
			elif sender == self.uprightField:
				self.uprightSlider.setDoubleValue_(max(0., min(100., v)))
			elif sender == self.balanceField:
				self.balanceSlider.setDoubleValue_(max(0., min(100., v)))
			else:
				for key, f in self._fields.items():
					if sender == f:
						self._values[key] = max(0., min(100. if key == 'terminals' else 150., v))
		except (ValueError, TypeError):
			pass
		self.angleField.setStringValue_("%g°" % self._angle)
		for key, f in self._fields.items():
			f.setStringValue_("%g%%" % self._values[key])
		self.balanceChanged_(sender)

	# ------------------------------------------------------------ analysis

	@objc.python_method
	def pathSegments(self, path):
		nodes = list(path.nodes)
		onIdx = [i for i, n in enumerate(nodes) if n.type != OFFCURVE]
		if len(onIdx) < 2:
			return None
		segs = []
		cnt = len(nodes)
		for k in range(len(onIdx)):
			a = onIdx[k]
			b = onIdx[(k + 1) % len(onIdx)]
			between = []
			i = (a + 1) % cnt
			while i != b:
				between.append(i)
				i = (i + 1) % cnt
			A, B = nodes[a], nodes[b]
			seg = {'iA': a, 'iB': b, 'A': (A.position.x, A.position.y), 'B': (B.position.x, B.position.y),
				'c1': None, 'c2': None, 'i1': None, 'i2': None}
			if len(between) == 2:
				seg['i1'], seg['i2'] = between
				seg['c1'] = (nodes[between[0]].position.x, nodes[between[0]].position.y)
				seg['c2'] = (nodes[between[1]].position.x, nodes[between[1]].position.y)
			elif between:
				return None
			segs.append(seg)
		return segs

	# ------------------------------------------------------------ core

	@objc.python_method
	def italicize(self, layer, angleDeg, curve, keepTerm, diag, stem, restoreVerticals, upright=0.):
		values = (angleDeg, curve, keepTerm, diag, stem)
		if not all(math.isfinite(v) for v in values) or abs(angleDeg) > 45:
			raise ValueError("Use a finite angle between −45° and 45°")
		if any(not isinstance(shape, GSPath) for shape in layer.shapes):
			raise ValueError("Decompose components in a copy before using Curse")
		for path in layer.shapes:
			if any(n.type not in (LINE, CURVE, OFFCURVE) for n in path.nodes):
				raise ValueError("Curse needs cubic or straight outlines")
			if any(not math.isfinite(v) for n in path.nodes for v in (n.position.x, n.position.y)):
				raise ValueError("Outline contains a non-finite coordinate")
			if path.closed and self.pathSegments(path) is None:
				raise ValueError("Outline contains an incomplete curve")
		th = math.radians(angleDeg)
		if abs(th) < 1e-6:
			return
		k = math.tan(th)
		try:
			y0 = layer.associatedFontMaster().xHeight / 2.0
		except Exception:
			b = layer.bounds
			y0 = b.origin.y + b.size.height / 2.0

		paths = [s for s in layer.shapes if isinstance(s, GSPath)]
		uprightOriginal = [[(n.position.x, n.position.y) for n in p.nodes] for p in paths if p.closed]
		slantedOriginal = [[(n.position.x + (n.position.y-y0)*k, n.position.y) for n in p.nodes] for p in paths if p.closed]
		closed = [p for p in paths if p.closed]

		def signedArea(path):
			pts = [(n.position.x, n.position.y) for n in path.nodes if n.type != OFFCURVE]
			a = 0.0
			for i in range(len(pts)):
				x1, y1 = pts[i]
				x2, y2 = pts[(i + 1) % len(pts)]
				a += x1 * y2 - x2 * y1
			return a / 2.0
		ccwOuter = True
		if closed:
			areas = [signedArea(p) for p in closed]
			ccwOuter = areas[max(range(len(closed)), key=lambda i: abs(areas[i]))] > 0

		def whiteN(t):
			return (t[1], -t[0]) if ccwOuter else (-t[1], t[0])

		# ---- flatten upright for ray casts (terminal detection, line widths)
		pathSegs = []
		pieces = []
		for path in closed:
			segs = self.pathSegments(path)
			pathSegs.append(segs)
			if segs is None:
				continue
			for seg in segs:
				if seg['c1'] is None:
					pts = [seg['A'], seg['B']]
				else:
					C = (seg['A'], seg['c1'], seg['c2'], seg['B'])
					pts = [_bez(C, j / float(FLAT)) for j in range(FLAT + 1)]
				for a, b in zip(pts, pts[1:]):
					t = _unit(b[0] - a[0], b[1] - a[1])
					if t is not None:
						pieces.append((a, b, whiteN(t)))

		def cast(P, nW):
			d = (-nW[0], -nW[1])
			best = None
			for a, b, nP in pieces:
				s = _raySeg(P, d, a, b)
				if s is None or s < 0.75:
					continue
				if best is None or s < best[0]:
					best = (s, nP)
			if best is None:
				return None
			facing = -(best[1][0] * nW[0] + best[1][1] * nW[1])
			if facing < 0.2:
				return None
			return (best[0], facing)

		def smooth01(x):
			x = max(0.0, min(1.0, x))
			return x * x * (3.0 - 2.0 * x)

		# per-segment casts at the middle
		for segs in pathSegs:
			if segs is None:
				continue
			for seg in segs:
				if seg['c1'] is None:
					M = ((seg['A'][0] + seg['B'][0]) / 2.0, (seg['A'][1] + seg['B'][1]) / 2.0)
					tM = _unit(seg['B'][0] - seg['A'][0], seg['B'][1] - seg['A'][1])
				else:
					C = (seg['A'], seg['c1'], seg['c2'], seg['B'])
					M = _bez(C, 0.5)
					tM = _unit(*_bezD(C, 0.5))
				seg['tM'] = tM
				seg['castM'] = cast(M, whiteN(tM)) if tM else None
		allD = [seg['castM'][0] for segs in pathSegs if segs for seg in segs
			if seg['castM'] is not None and seg['castM'][1] > 0.7]
		medFull = _median(allD) if allD else None

		def strokeLikeness(c):
			if c is None or not medFull:
				return 1.0
			d, facing = c
			sF = smooth01((facing - 0.5) / 0.35)
			sL = 1.0 - smooth01((d / medFull - 1.4) / 1.1)
			return min(sF, sL)

		# remember which nodes had vertical tangents (for keep-extremes)
		verticalNodes = []
		if restoreVerticals:
			for path in closed:
				nodes = list(path.nodes)
				cnt = len(nodes)
				for i, n in enumerate(nodes):
					if n.type == OFFCURVE or not n.smooth:
						continue
					p, q = nodes[(i - 1) % cnt], nodes[(i + 1) % cnt]
					if p.type != OFFCURVE or q.type != OFFCURVE:
						continue
					dxi, dyi = abs(p.position.x - n.position.x), abs(p.position.y - n.position.y)
					dxo, dyo = abs(q.position.x - n.position.x), abs(q.position.y - n.position.y)
					if dxi <= 0.09 * dyi and dxo <= 0.09 * dyo:
						verticalNodes.append((path, i))

		# ================= 1. curve correction on the upright =================
		# extension bounds: the glyph's box, grown by half its size each way
		extBounds = None
		allPts = [(n.position.x, n.position.y) for p in closed for n in p.nodes]
		if allPts:
			xs = [q[0] for q in allPts]
			ys = [q[1] for q in allPts]
			gw, gh = max(xs) - min(xs), max(ys) - min(ys)
			extBounds = (min(xs) - 0.5 * gw, min(ys) - 0.5 * gh, max(xs) + 0.5 * gw, max(ys) + 0.5 * gh)
		if curve > 0 and closed:
			origin = ((min(x[0] for x in allPts) + max(x[0] for x in allPts)) / 2., y0)
			for path, segs in zip(closed, pathSegs):
				weights = {seg['iA']: 1. - keepTerm * (1. - strokeLikeness(seg['castM'])) for seg in segs}
				_correctRuns(path, th * curve, angleDeg, stem, origin, weights, self._clipToLine)

		# ================= 2. slant everything =================
		for path in paths:
			for n in path.nodes:
				p = n.position
				n.position = NSMakePoint(p.x + (p.y - y0) * k, p.y)
		try:
			for a in layer.anchors:
				p = a.position
				a.position = NSMakePoint(p.x + (p.y - y0) * k, p.y)
		except Exception:
			pass

		# ================= 3. straight segments: diagonal / stem =================
		if (diag > 0 or stem > 0) and medFull:
			hwBase = medFull / 2.0
			for path, segs in zip(closed, pathSegs):
				if segs is None:
					continue
				nodes = list(path.nodes)
				cnt = len(nodes)
				moves = {}
				for seg in segs:
					if seg['c1'] is not None:
						continue
					t = _unit(seg['B'][0] - seg['A'][0], seg['B'][1] - seg['A'][1])
					if t is None:
						continue
					kind = _axisKind(t)
					if kind == 'h':
						continue
					amount = stem if kind == 'v' else diag
					if amount <= 0:
						continue
					c = seg['castM']
					if c is None:
						hw = hwBase
					else:
						hw = min(c[0] / 2.0, WIDTH_CAP * hwBase) * strokeLikeness(c) + hwBase * (1 - strokeLikeness(c))
					sx, sy = t[0] + k * t[1], t[1]
					L = math.hypot(sx, sy)
					delta = amount * hw * (1.0 - 1.0 / L)
					tp = _unit(sx, sy)
					npx, npy = whiteN(tp)
					for idx in (seg['iA'], seg['iB']):
						moves.setdefault(idx, []).append((delta * npx, delta * npy, tp))
				# apply: single move -> translate node (+ its curve handles); two lines
				# meeting at a corner -> intersect the two offset lines
				for idx, mv in moves.items():
					n = nodes[idx]
					p = (n.position.x, n.position.y)
					if len(mv) == 1:
						d = (mv[0][0], mv[0][1])
					else:
						(d1x, d1y, t1), (d2x, d2y, t2) = mv[0], mv[1]
						hit = _rayInt((p[0] + d1x, p[1] + d1y), t1, (p[0] + d2x, p[1] + d2y), t2)
						if hit is None or math.hypot(hit[0][0] - p[0], hit[0][1] - p[1]) > 4 * max(math.hypot(d1x, d1y), math.hypot(d2x, d2y)) + 2:
							d = ((d1x + d2x) / 2.0, (d1y + d2y) / 2.0)
						else:
							d = (hit[0][0] - p[0], hit[0][1] - p[1])
					n.position = NSMakePoint(p[0] + d[0], p[1] + d[1])
					for j in ((idx - 1) % cnt, (idx + 1) % cnt):
						h = nodes[j]
						if h.type == OFFCURVE:
							h.position = NSMakePoint(h.position.x + d[0], h.position.y + d[1])

		# ================= 4. keep extremes =================
		# Slide each formerly-vertical-extreme node along the
		# corrected outline to the true x-extreme and refit the two adjoining
		# cubics; only commit if the outline moves by <= EXTREME_TOL units.
		for path, i in verticalNodes:
			self._keepExtreme(path, i)

		if closed and curve > 0:
			new = [[(n.position.x, n.position.y) for n in p.nodes] for p in closed]
			types = [[n.type for n in p.nodes] for p in closed]
			smooth = [[n.smooth for n in p.nodes] for p in closed]
			safe, _ = _safe_contours(slantedOriginal, new, types, smooth)
			for path, pts in zip(closed, safe):
				for node, point in zip(path.nodes, pts):
					node.position = NSMakePoint(*point)

		if closed and upright > 0:
			corrected = [[(n.position.x, n.position.y) for n in p.nodes] for p in closed]
			result = _upright_bowls(uprightOriginal, corrected, [[n.type for n in p.nodes] for p in closed], [[n.smooth for n in p.nodes] for p in closed], angleDeg, y0, min(1., upright))
			for path, pts in zip(closed, result):
				for node, point in zip(path.nodes, pts):
					node.position = NSMakePoint(*point)

	@objc.python_method
	def _keepExtreme(self, path, i):
		nodes = list(path.nodes)
		cnt = len(nodes)
		n = nodes[i]
		a2, a1, a0 = nodes[(i - 1) % cnt], nodes[(i - 2) % cnt], nodes[(i - 3) % cnt]
		b1, b2, b3 = nodes[(i + 1) % cnt], nodes[(i + 2) % cnt], nodes[(i + 3) % cnt]
		if (a1.type != OFFCURVE or a2.type != OFFCURVE or a0.type == OFFCURVE
				or b1.type != OFFCURVE or b2.type != OFFCURVE or b3.type == OFFCURVE):
			return
		P = lambda q: (q.position.x, q.position.y)
		C1 = (P(a0), P(a1), P(a2), P(n))
		C2 = (P(n), P(b1), P(b2), P(b3))
		# find the x-extreme on the chain nearest to the node
		best = None
		for C, seg in ((C1, 0), (C2, 1)):
			for r in _extremeParams(C):
				# only x-extremes: x'(r) == 0
				dx, dy = _bezD(C, r)
				if abs(dx) > 1e-6 * max(1.0, abs(dy)) or not (-0.05 <= r <= 1.05):
					continue
				# distance along the chain from the node
				dist = (1 - r) if seg == 0 else r
				if best is None or dist < best[0]:
					best = (dist, seg, r)
		if best is None:
			return
		_, seg, r = best
		if (seg == 0 and r > 1 - 1e-4) or (seg == 1 and r < 1e-4):
			return  # already at the extreme
		# Distance limit: on a nearly straight run (a u's left side, a b's stem)
		# the outline hardly changes however far the node slides, so the
		# deviation test alone would allow it to travel most of the letter.
		Ptarget = _bez(C1 if seg == 0 else C2, r)
		slide = math.hypot(Ptarget[0] - P(n)[0], Ptarget[1] - P(n)[1])
		host = C1 if seg == 0 else C2
		hostChord = math.hypot(host[3][0] - host[0][0], host[3][1] - host[0][1])
		if slide > EXTREME_SLIDE * hostChord:
			return
		# samples along the two original cubics for the refit
		def samples(C, t0, t1, k=24):
			return [_bez(C, t0 + (t1 - t0) * j / float(k)) for j in range(k + 1)]
		if seg == 0:
			# extreme lies on C1: C1 shortens to [0, r]; C2 grows to cover C1[r,1] + C2
			Pn = _bez(C1, r)
			left = _sub(C1, 0.0, r)
			s2 = samples(C1, r, 1.0) + samples(C2, 0.0, 1.0)[1:]
			tEnd = _unit(P(b3)[0] - P(b2)[0], P(b3)[1] - P(b2)[1])
			right = _fitCubicFree(s2, Pn, P(b3), (0.0, 1.0 if _bezD(C1, r)[1] > 0 else -1.0),
				(-tEnd[0], -tEnd[1]) if tEnd else None)
			if right is None:
				return
			newC1, newC2 = left, right
			ref1, ref2 = samples(C1, 0.0, r), s2
		else:
			Pn = _bez(C2, r)
			right = _sub(C2, r, 1.0)
			s1 = samples(C1, 0.0, 1.0) + samples(C2, 0.0, r)[1:]
			tStart = _unit(P(a1)[0] - P(a0)[0], P(a1)[1] - P(a0)[1])
			dyr = _bezD(C2, r)[1]
			left = _fitCubicFree(s1, P(a0), Pn, tStart, (0.0, -1.0 if dyr > 0 else 1.0))
			if left is None:
				return
			newC1, newC2 = left, right
			ref1, ref2 = s1, samples(C2, r, 1.0)
		# deviation check against the reference samples
		dev = max(self._maxDev(newC1, ref1), self._maxDev(newC2, ref2))
		if dev > EXTREME_TOL:
			return
		a1.position = NSMakePoint(*newC1[1])
		a2.position = NSMakePoint(*newC1[2])
		n.position = NSMakePoint(*Pn)
		b1.position = NSMakePoint(*newC2[1])
		b2.position = NSMakePoint(*newC2[2])
		n.smooth = True

	@objc.python_method
	def _maxDev(self, C, ref):
		"""Max distance from the reference points to the cubic (measured
		against a dense polyline of the cubic, point-to-segment)."""
		dense = [_bez(C, j / 120.0) for j in range(121)]
		worst = 0.0
		for pt in ref:
			best = None
			for a, b in zip(dense, dense[1:]):
				vx, vy = b[0] - a[0], b[1] - a[1]
				L2 = vx * vx + vy * vy
				if L2 < 1e-12:
					d = math.hypot(pt[0] - a[0], pt[1] - a[1])
				else:
					t = max(0.0, min(1.0, ((pt[0] - a[0]) * vx + (pt[1] - a[1]) * vy) / L2))
					d = math.hypot(pt[0] - a[0] - t * vx, pt[1] - a[1] - t * vy)
				if best is None or d < best:
					best = d
			worst = max(worst, best)
		return worst

	@objc.python_method
	def _clipToLine(self, E2, u, LA, LB):
		"""Parameter on cubic E2 (searching around u, on the extrapolated
		curve if needed) where it crosses the infinite line through LA-LB.
		Returns None when there is no crossing nearby."""
		d = _unit(LB[0] - LA[0], LB[1] - LA[1])
		if d is None:
			return None
		nx, ny = -d[1], d[0]

		def sd(t):
			P = _bez(E2, t)
			return (P[0] - LA[0]) * nx + (P[1] - LA[1]) * ny
		# expanding bracket search around u (up to +-1.5 in parameter)
		for half in (0.15, 0.4, 0.8, 1.5):
			lo, hi = u - half, u + half
			flo, fhi = sd(lo), sd(hi)
			if flo * fhi <= 0:
				for _ in range(50):
					mid = (lo + hi) / 2.0
					fm = sd(mid)
					if flo * fm <= 0:
						hi, fhi = mid, fm
					else:
						lo, flo = mid, fm
				return (lo + hi) / 2.0
		return None

	# ------------------------------------------------------------ filter

	@objc.python_method
	def filter(self, layer, inEditView, customParameters):
		params = customParameters or {}
		try:
			def P(key, fallback):
				value = float(params.get(key, fallback))
				if not math.isfinite(value):
					raise ValueError("Parameters must be finite numbers")
				return value
			defaults = {'curve': 100., 'terminals': 0., 'diagonal': 100., 'stem': 0.}
			def amount(key):
				fallback = self.val(key) if inEditView and hasattr(self, '_values') else defaults[key]
				return max(0., min(100. if key == 'terminals' else 150., P(key, fallback))) / 100.
			angle = P('angle', getattr(self, '_angle', 12.) if inEditView else 12.)
			verts = bool(self.vertCheck.state()) if inEditView and hasattr(self, 'vertCheck') else False
			if 'extremes' in params:
				verts = str(params['extremes']).strip().lower() in ('1', 'true', 'yes')
			# A zero Balance is exactly a plain slant, including when refitting is checked.
			if inEditView and not params and hasattr(self, 'balanceSlider') and self.balanceSlider.doubleValue() == 0:
				verts = False
			upright = self.uprightSlider.doubleValue() * self.balanceSlider.doubleValue() / 100. if inEditView and hasattr(self, 'uprightSlider') else 0.
			upright = max(0., min(100., P('upright', upright))) / 100.
			if inEditView and not params and hasattr(self, 'balanceSlider') and self.balanceSlider.doubleValue() == 0:
				upright = 0.
			self.italicize(layer, angle, amount('curve'), amount('terminals'), amount('diagonal'), amount('stem'), verts, upright)
			if inEditView and hasattr(self, 'status'):
				self.status.setStringValue_("Preview ready. Apply keeps this result.")
		except Exception as exc:
			if inEditView and hasattr(self, 'status'):
				self.status.setStringValue_(str(exc))
				self.status.setToolTip_(str(exc))
			if not inEditView:
				raise
			print("Curse: %s" % exc)

	@objc.python_method
	def generateCustomParameter(self):
		return "%s; angle:%g; curve:%g; terminals:%g; diagonal:%g; stem:%g; extremes:%d; upright:%g" % (
			self.__class__.__name__, self._angle, self.val('curve'), self.val('terminals'),
			self.val('diagonal'), self.val('stem'),
			1 if self.vertCheck.state() and self.balanceSlider.doubleValue() > 0 else 0,
			self.uprightSlider.doubleValue() * self.balanceSlider.doubleValue() / 100.)

	@objc.python_method
	def __file__(self):
		return __file__
