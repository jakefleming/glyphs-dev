# encoding: utf-8
from __future__ import division, print_function, unicode_literals

"""
Curse — optically corrected oblique.

Curve correction (the core, same construction Italify uses):
  work on the UPRIGHT outline first, then slant. Every cubic is extended
  (as the same polynomial) to the implicit horizontal/vertical extremes
  beyond its ends when it does not end on one; the extended arc's two end
  tangent lines meet at a corner C. All four control points of the extended
  arc are scaled about C by f = 1 + s*theta_rad*curve, where s = +1 if C lies
  in a "/" quadrant relative to the arc (bottom-left / top-right) and -1 in a
  "\\" quadrant. The original segment is then clipped back out of the
  corrected extended arc (re-intersected with an adjoining straight line if
  there is one). Net effect after the slant: bowls come out rotated by about
  half the angle instead of sheared. Nodes shared by two arcs take the
  smaller of the two proposals. Lines are untouched here.

Keep terminals: caps / terminals (arcs whose ray cast does not land on the
  opposite side of their own stroke) get their curve correction faded out.
Diagonal correction: straight diagonal segments get their perpendicular
  stroke width restored after the slant (delta = w*(1 - 1/|S t|)).
Stem compensation: the same for near-vertical straight segments.
Keep nodes on extremes: put vertical extremes back after the slant.
"""

import objc
import math
import traceback
from GlyphsApp import Glyphs, GSPath, LINE, CURVE, OFFCURVE
from GlyphsApp.plugins import FilterWithDialog
from AppKit import NSView, NSSlider, NSTextField, NSButton, NSMakeRect, NSFont
from Foundation import NSMakePoint

FLAT = 12         # polyline pieces per curve for ray casts
AXIS_TOL = 0.035  # |sin| below this counts as an axis-aligned tangent (~2 deg)
EXT_LIMIT = 4.0   # max extension in units of segment parameter
WIDTH_CAP = 1.5   # local half-width clamp (x median) for the line corrections
EXTREME_TOL = 2.0 # keep-extremes: max outline deviation allowed when re-placing a node


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
	"""Control points of the cubic restricted/extended to [t0, t1] (any reals)."""
	def lerp(a, b, t):
		return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

	def split_left(P, t):
		p01, p12, p23 = lerp(P[0], P[1], t), lerp(P[1], P[2], t), lerp(P[2], P[3], t)
		p012, p123 = lerp(p01, p12, t), lerp(p12, p23, t)
		return (P[0], p01, p012, lerp(p012, p123, t))

	def split_right(P, t):
		p01, p12, p23 = lerp(P[0], P[1], t), lerp(P[1], P[2], t), lerp(P[2], P[3], t)
		p012, p123 = lerp(p01, p12, t), lerp(p12, p23, t)
		return (lerp(p012, p123, t), p123, p23, P[3])
	# de Casteljau works for parameters outside [0,1] as extrapolation
	R = split_right(C, t0)
	if abs(1 - t0) < 1e-12:
		return R
	u = (t1 - t0) / (1 - t0)
	return split_left(R, u)


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


def _extend(C):
	"""Extend a cubic to its implicit extremes: returns (t0, t1) with t0<=0,
	t1>=1 such that the tangents at t0 and t1 are axis-aligned when such
	extremes exist within EXT_LIMIT; otherwise the end stays where it is."""
	t0, t1 = 0.0, 1.0
	dA = _unit(*_bezD(C, 0.0))
	dB = _unit(*_bezD(C, 1.0))
	roots = _extremeParams(C)
	if _axisKind(dA) is None:
		cands = [r for r in roots if r < -1e-6 and r >= -EXT_LIMIT]
		if cands:
			t0 = max(cands)
	if _axisKind(dB) is None:
		cands = [r for r in roots if r > 1 + 1e-6 and r <= 1 + EXT_LIMIT]
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


class MakeItalic(FilterWithDialog):

	# ------------------------------------------------------------ UI

	@objc.python_method
	def settings(self):
		self.menuName = "Curse"
		self.actionButtonLabel = "Apply"

		W = 300
		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 300))
		self._rows = {}

		def label(text, y, size=12, alpha=1.0):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(14, y, W - 100, 18))
			f.setStringValue_(text)
			f.setBezeled_(False)
			f.setDrawsBackground_(False)
			f.setEditable_(False)
			f.setSelectable_(False)
			f.setFont_(NSFont.systemFontOfSize_(size))
			if alpha < 1.0:
				f.setTextColor_(f.textColor().colorWithAlphaComponent_(alpha))
			view.addSubview_(f)
			return f

		def field(y, text, w=54):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(W - 14 - w, y, w, 21))
			f.setStringValue_(text)
			f.setAlignment_(1)
			f.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0.0))
			f.setTarget_(self)
			f.setAction_("fieldChanged:")
			view.addSubview_(f)
			return f

		def row(key, title, y, lo, hi, val, suffix):
			label(title, y + 24)
			s = NSSlider.alloc().initWithFrame_(NSMakeRect(14, y, W - 90, 20))
			s.setMinValue_(lo)
			s.setMaxValue_(hi)
			s.setDoubleValue_(val)
			s.setContinuous_(True)
			s.setTarget_(self)
			s.setAction_("sliderChanged:")
			view.addSubview_(s)
			f = field(y, "%d%s" % (val, suffix))
			self._rows[key] = (s, f, suffix, val)

		# angle: value field only, like the reference
		label("Angle", 268)
		self.angleField = field(266, "12°")
		self._angle = 12.0

		row('curve', "Curve correction", 216, 0, 150, 100, "%")
		row('terminals', "Keep terminals", 168, 0, 100, 0, "%")
		row('diagonal', "Diagonal correction", 108, 0, 150, 100, "%")
		row('stem', "Stem compensation", 60, 0, 150, 0, "%")

		self.vertCheck = NSButton.alloc().initWithFrame_(NSMakeRect(14, 22, W - 28, 20))
		self.vertCheck.setButtonType_(3)
		self.vertCheck.setTitle_("Keep nodes on extremes")
		self.vertCheck.setState_(0)
		self.vertCheck.setTarget_(self)
		self.vertCheck.setAction_("sliderChanged:")
		view.addSubview_(self.vertCheck)

		self.dialog = view

	@objc.python_method
	def start(self):
		try:
			ia = Glyphs.font.selectedFontMaster.italicAngle
			if ia and 0 < abs(ia) <= 45:
				self._angle = abs(ia)
				self.angleField.setStringValue_("%g°" % round(self._angle, 1))
		except Exception:
			pass

	@objc.python_method
	def val(self, key):
		return self._rows[key][0].doubleValue()

	def sliderChanged_(self, sender):
		for key, (s, f, suffix, _d) in self._rows.items():
			f.setStringValue_("%d%s" % (round(s.doubleValue()), suffix))
		self.update()

	def fieldChanged_(self, sender):
		raw = sender.stringValue().replace("°", "").replace("%", "").strip()
		try:
			v = float(raw)
		except ValueError:
			self.sliderChanged_(sender)
			self.angleField.setStringValue_("%g°" % round(self._angle, 1))
			return
		if sender is self.angleField:
			self._angle = max(0.0, min(45.0, v))
			self.angleField.setStringValue_("%g°" % round(self._angle, 1))
			self.update()
			return
		for key, (s, f, suffix, _d) in self._rows.items():
			if sender is f:
				s.setDoubleValue_(max(s.minValue(), min(s.maxValue(), v)))
		self.sliderChanged_(sender)

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
	def italicize(self, layer, angleDeg, curve, keepTerm, diag, stem, restoreVerticals):
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
		if curve > 0:
			for path, segs in zip(closed, pathSegs):
				if segs is None:
					continue
				nodes = list(path.nodes)
				nseg = len(segs)
				proposals = {}   # node index -> list of (dx, dy)
				handleMove = {}  # offcurve index -> (dx, dy, nodeIndex, nodeOwnProposal)

				def farTangentLine(other, atStart):
					"""Tangent line (point, dir) at the far end of a neighbouring
					segment: its A end if atStart else its B end."""
					if other['c1'] is None:
						d = _unit(other['B'][0] - other['A'][0], other['B'][1] - other['A'][1])
						return (other['A'] if atStart else other['B']), d
					if atStart:
						return other['A'], _unit(other['c1'][0] - other['A'][0], other['c1'][1] - other['A'][1])
					return other['B'], _unit(other['B'][0] - other['c2'][0], other['B'][1] - other['c2'][1])

				for si, seg in enumerate(segs):
					if seg['c1'] is None:
						continue
					A, c1, c2, B = seg['A'], seg['c1'], seg['c2'], seg['B']
					C = (A, c1, c2, B)
					tA = _unit(c1[0] - A[0], c1[1] - A[1]) or _unit(B[0] - A[0], B[1] - A[1])
					tB = _unit(B[0] - c2[0], B[1] - c2[1]) or _unit(B[0] - A[0], B[1] - A[1])
					if tA is None or tB is None:
						continue

					def noCorner():
						# no usable corner (inflection / degenerate): this segment
						# makes no proposal; its neighbours decide the shared nodes
						pass

					t0, t1 = _extend(C)
					E = _sub(C, t0, t1)
					dE0 = _unit(*_bezD(E, 0.0))
					dE3 = _unit(*_bezD(E, 1.0))
					if dE0 is None or dE3 is None:
						noCorner()
						continue
					hit = _rayInt(E[0], dE0, E[3], (-dE3[0], -dE3[1]))
					if hit is None:
						noCorner()
						continue
					corner, a, b = hit
					if a <= 0 or b <= 0:
						noCorner()  # tangents diverge: inflection / degenerate
						continue
					mid = ((E[0][0] + E[3][0]) / 2.0, (E[0][1] + E[3][1]) / 2.0)
					dx, dy = corner[0] - mid[0], corner[1] - mid[1]
					if abs(dx) < 1e-6 or abs(dy) < 1e-6:
						noCorner()
						continue
					s = 1.0 if dx * dy > 0 else -1.0
					capness = 1.0 - strokeLikeness(seg['castM'])
					strength = th * curve * (1.0 - keepTerm * capness)
					prev, nxt = segs[si - 1], segs[(si + 1) % nseg]

					def endMove(N, tN, H, otherSeg, atStart):
						"""Move for node N (tangent tN) and its handle H along the
						tangent line: theta' x min(distance to the corner's foot on
						this line, distance to the neighbour's far tangent line)."""
						proj = (corner[0] - N[0]) * tN[0] + (corner[1] - N[1]) * tN[1]
						Cleg = (N[0] + tN[0] * proj, N[1] + tN[1] * proj)
						toward = 1.0 if proj >= 0 else -1.0
						dN = abs(proj)
						dH = abs((Cleg[0] - H[0]) * tN[0] + (Cleg[1] - H[1]) * tN[1])
						fp, fd = farTangentLine(otherSeg, atStart)
						if fd is not None:
							far = _rayInt(N, tN, fp, fd)
							if far is not None:
								F = far[0]
								dF = abs((F[0] - N[0]) * tN[0] + (F[1] - N[1]) * tN[1])
								dN = min(dN, dF)
								dH = min(dH, abs((F[0] - H[0]) * tN[0] + (F[1] - H[1]) * tN[1]))
						sign = -s * toward   # shrink (s=-1) -> toward the corner
						return ((sign * strength * dN * tN[0], sign * strength * dN * tN[1]),
							(sign * strength * dH * tN[0], sign * strength * dH * tN[1]))

					mvA, mv1 = endMove(A, tA, c1, prev, True)
					mvB, mv2 = endMove(B, tB, c2, nxt, False)
					proposals.setdefault(seg['iA'], []).append(mvA)
					proposals.setdefault(seg['iB'], []).append(mvB)
					handleMove[seg['i1']] = (mv1[0], mv1[1], seg['iA'], mvA)
					handleMove[seg['i2']] = (mv2[0], mv2[1], seg['iB'], mvB)

				# commit: nodes take the smallest proposal; handles follow their own
				# segment's move, corrected by however far the node ended up from
				# that segment's own wish (keeps the tangent direction intact)
				chosen = {}
				for idx, props in proposals.items():
					chosen[idx] = min(props, key=lambda v: math.hypot(v[0], v[1]))
				for hidx, (hx, hy, nidx, own) in handleMove.items():
					d = chosen.get(nidx, (0.0, 0.0))
					h = nodes[hidx].position
					nodes[hidx].position = NSMakePoint(h.x + hx + (d[0] - own[0]), h.y + hy + (d[1] - own[1]))
				for idx, d in chosen.items():
					p = nodes[idx].position
					nodes[idx].position = NSMakePoint(p.x + d[0], p.y + d[1])

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
		# Italify-style: slide each formerly-vertical-extreme node along the
		# corrected outline to the true x-extreme and refit the two adjoining
		# cubics; only commit if the outline moves by <= EXTREME_TOL units.
		for path, i in verticalNodes:
			self._keepExtreme(path, i)

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
		"""Parameter on cubic E2 (near u) where it crosses the line LA-LB."""
		d = _unit(LB[0] - LA[0], LB[1] - LA[1])
		if d is None:
			return u
		nx, ny = -d[1], d[0]

		def sd(t):
			P = _bez(E2, t)
			return (P[0] - LA[0]) * nx + (P[1] - LA[1]) * ny
		# bracket around u
		lo, hi = u - 0.35, u + 0.35
		flo, fhi = sd(lo), sd(hi)
		if flo * fhi > 0:
			return u
		for _ in range(40):
			mid = (lo + hi) / 2.0
			fm = sd(mid)
			if flo * fm <= 0:
				hi, fhi = mid, fm
			else:
				lo, flo = mid, fm
		return (lo + hi) / 2.0

	# ------------------------------------------------------------ filter

	@objc.python_method
	def filter(self, layer, inEditView, customParameters):
		try:
			def P(key, default):
				if key in customParameters:
					return float(customParameters[key])
				return default
			angle = P('angle', self._angle)
			curve = P('curve', self.val('curve')) / 100.0
			term = P('terminals', self.val('terminals')) / 100.0
			diag = P('diagonal', self.val('diagonal')) / 100.0
			stem = P('stem', self.val('stem')) / 100.0
			if 'extremes' in customParameters:
				verts = str(customParameters['extremes']).strip() in ("1", "true", "yes")
			else:
				verts = bool(self.vertCheck.state())
			self.italicize(layer, angle, curve, term, diag, stem, verts)
		except Exception:
			print(traceback.format_exc())

	@objc.python_method
	def generateCustomParameter(self):
		return "%s; angle:%g; curve:%d; terminals:%d; diagonal:%d; stem:%d; extremes:%d" % (
			self.__class__.__name__, round(self._angle, 1), round(self.val('curve')),
			round(self.val('terminals')), round(self.val('diagonal')), round(self.val('stem')),
			1 if self.vertCheck.state() else 0)

	@objc.python_method
	def __file__(self):
		return __file__
