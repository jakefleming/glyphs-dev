"""Conservative curve-weight correction. No Glyphs or third-party dependencies."""
import copy
import math
from collections import defaultdict
from statistics import median


def sub(a, b): return (a[0] - b[0], a[1] - b[1])
def add(a, b): return (a[0] + b[0], a[1] + b[1])
def mul(a, v): return (a[0] * v, a[1] * v)
def dot(a, b): return a[0] * b[0] + a[1] * b[1]
def cross(a, b): return a[0] * b[1] - a[1] * b[0]
def length(a): return math.hypot(*a)
def unit(a): return mul(a, 1.0 / max(length(a), 1e-12))
def point(n): return (n['x'], n['y'])


def segments(paths):
    out = []
    for pi, path in enumerate(paths):
        if not path['closed']:
            raise ValueError('Open contours are not supported.')
        nodes = path['nodes']
        on = [i for i, n in enumerate(nodes) if n['type'] != 'offcurve']
        if len(on) < 2:
            raise ValueError('Contour has too few points.')
        for k, a in enumerate(on):
            b = on[(k + 1) % len(on)]
            ids = [a]
            j = (a + 1) % len(nodes)
            while j != b:
                ids.append(j)
                j = (j + 1) % len(nodes)
            ids.append(b)
            if not ((len(ids) == 2 and nodes[b]['type'] == 'line') or
                    (len(ids) == 4 and nodes[b]['type'] == 'curve')):
                raise ValueError('Only line and cubic contours are supported.')
            out.append({'path': pi, 'ids': ids, 'pts': [point(nodes[i]) for i in ids]})
    return out


def weights(s, t):
    if len(s['ids']) == 2: return [1-t, t]
    u = 1-t
    return [u**3, 3*u*u*t, 3*u*t*t, t**3]


def evaluate(s, t):
    w = weights(s, t)
    return (sum(v*p[0] for v,p in zip(w,s['pts'])), sum(v*p[1] for v,p in zip(w,s['pts'])))


def tangent(s, t):
    p = s['pts']
    if len(p) == 2: return unit(sub(p[1],p[0]))
    u=1-t
    return unit(add(add(mul(sub(p[1],p[0]),3*u*u),mul(sub(p[2],p[1]),6*u*t)),mul(sub(p[3],p[2]),3*t*t)))


def mesh(ss, steps=16):
    edges=[]
    for si,s in enumerate(ss):
        count=steps if len(s['pts'])==4 else 1
        for j in range(count):
            edges.append((evaluate(s,j/count),evaluate(s,(j+1)/count),si,j/count,(j+1)/count))
    return edges


def inside(p, edges):
    # Nonzero winding follows the font's contour directions.
    winding=0
    for a,b,*_ in edges:
        if a[1]<=p[1]<b[1] and cross(sub(b,a),sub(p,a))>0: winding+=1
        elif b[1]<=p[1]<a[1] and cross(sub(b,a),sub(p,a))<0: winding-=1
    return winding != 0


def crossing_count(edges):
    count=0
    for i,(a,b,*_) in enumerate(edges):
        for c,d,*_ in edges[i+1:]:
            r,s=sub(b,a),sub(d,c)
            den=cross(r,s)
            if abs(den)<1e-9: continue
            u,v=cross(sub(c,a),s)/den,cross(sub(c,a),r)/den
            if 1e-6<u<1-1e-6 and 1e-6<v<1-1e-6: count+=1
    return count


def observations(paths, upm=1000):
    ss=segments(paths); edges=mesh(ss)
    out=[]
    for si,s in enumerate(ss):
        curved=abs(dot(tangent(s,.1),tangent(s,.9)))<.98
        for t in (.15,.3,.5,.7,.85):
            p=evaluate(s,t); tan=tangent(s,t); normal=(-tan[1],tan[0])
            if length(tan)<.5: continue
            hits=[]
            for sign in (-1,1):
                n=mul(normal,sign)
                if not inside(add(p,mul(n,upm*.0005)),edges): continue
                for a,b,sj,ta,tb in edges:
                    if sj==si: continue
                    edge=sub(b,a); den=cross(n,edge)
                    if abs(den)<1e-9: continue
                    distance=cross(sub(a,p),edge)/den
                    u=cross(sub(a,p),n)/den
                    if upm*.006<distance<upm*.35 and 0<=u<=1:
                        hits.append((distance,sj,ta+(tb-ta)*u,n))
            if not hits: continue
            width,sj,tj,n=min(hits,key=lambda h:h[0])
            other=ss[sj]; other_tan=tangent(other,tj)
            if abs(dot(tan,other_tan))<.96 or not .08<tj<.92: continue
            # Both edges must bound ink rather than cross a counter or overlap.
            if not all(inside(add(p,mul(n,width*f)),edges) for f in (.2,.5,.8)): continue
            if inside(add(p,mul(n,width+upm*.001)),edges): continue
            angle=math.degrees(math.atan2(abs(n[1]),abs(n[0])))
            orientation='vertical' if angle<20 else ('horizontal' if angle>70 else 'diagonal')
            out.append({'s':si,'t':t,'other':sj,'u':tj,'n':n,'width':width,
                        'family':(orientation,'curve' if curved else 'straight')})
    return ss,out


def signature(paths):
    # Translation-independent duplicates (including identical alternates) vote once.
    pts=[point(n) for p in paths for n in p['nodes']]
    if not pts: return ()
    x=min(p[0] for p in pts);y=min(p[1] for p in pts)
    return tuple(tuple((round(n['x']-x,1),round(n['y']-y,1),n['type']) for n in p['nodes']) for p in paths)


def learn(glyphs, upm=1000):
    """Freeze robust per-family width bands; each distinct glyph contributes once."""
    families=defaultdict(list); seen=set(); inspected=0; skipped=0
    for g in glyphs:
        sig=(g['group'],signature(g['paths']))
        if sig in seen or not sig[1]: continue
        seen.add(sig)
        try:
            ss,obs=observations(g['paths'],upm)
            if crossing_count(mesh(ss)): skipped+=1;continue
        except ValueError:
            skipped+=1;continue
        inspected+=1
        local=defaultdict(list)
        for o in obs: local[(g['group'],)+o['family']].append(o['width'])
        for family,widths in local.items():
            if len(widths)>=3:
                center=median(widths)
                families[family].append((center,median(abs(v-center) for v in widths),g['name']))
    bands={}
    for family,values in families.items():
        # Complete-link clusters avoid joining two weights through intermediate values.
        clusters=[]
        for v in sorted(values):
            if not clusters or v[0]>clusters[-1][0][0]*1.15: clusters.append([v])
            else: clusters[-1].append(v)
        accepted=[]
        for cluster in clusters:
            if len(cluster)<4 or len(cluster)<len(values)*.2: continue
            center=median(v[0] for v in cluster)
            between=median(abs(v[0]-center) for v in cluster)
            within=median(v[1] for v in cluster)
            tolerance=max(upm*.002,center*.045,2.5*between,2*within)
            # Broadly dispersed families are evidence of uncertainty, not a target.
            if tolerance>center*.18: continue
            accepted.append({'center':center,'low':center-tolerance,'high':center+tolerance,
                             'support':len(cluster)})
        if accepted: bands[family]=accepted
    return {'bands':bands,'inspected':inspected,'skipped':skipped,'upm':upm}


def target_for(o, group, model):
    bands=model['bands'].get((group,)+o['family'],[])
    if not bands: return None
    b=min(bands,key=lambda b:abs(math.log(o['width']/b['center'])))
    if abs(o['width']/b['center']-1)>.25: return None
    return min(b['high'],max(b['low'],o['width']))


def variables(paths, ss):
    """Smooth cubic joins can translate; handles retain their original directions.
    Nodes touching lines stay fixed. Bounds and corner nodes stay fixed.
    """
    incident=defaultdict(list)
    allpts=[p for s in ss for p in s['pts']]
    bounds=(min(p[0] for p in allpts),max(p[0] for p in allpts),min(p[1] for p in allpts),max(p[1] for p in allpts))
    for s in ss:
        for i in (s['ids'][0],s['ids'][-1]): incident[(s['path'],i)].append(s)
    effects=defaultdict(dict); limits=[]
    def variable(nodes,direction,limit):
        idx=len(limits);limits.append(limit)
        for key in nodes: effects[key][idx]=direction
    for key,segs in incident.items():
        pi,i=key; node=paths[pi]['nodes'][i]
        if len(segs)!=2 or not node.get('smooth') or any(len(s['ids'])!=4 for s in segs):continue
        attached=[key]
        for s in segs:
            attached.append((pi,s['ids'][1] if s['ids'][0]==i else s['ids'][-2]))
        p=point(node)
        if min(abs(p[0]-bounds[0]),abs(p[0]-bounds[1]))>1e-6: variable(attached,(1,0),None)
        if min(abs(p[1]-bounds[2]),abs(p[1]-bounds[3]))>1e-6: variable(attached,(0,1),None)
    for s in ss:
        if len(s['ids'])!=4:continue
        for hi,ai in ((1,0),(2,3)):
            delta=sub(s['pts'][hi],s['pts'][ai]);size=length(delta)
            if size>1e-5: variable([(s['path'],s['ids'][hi])],unit(delta),size*.3)
    return effects,limits


def basis(s,t,effects):
    out={}
    for node,w in zip(s['ids'],weights(s,t)):
        for i,d in effects.get((s['path'],node),{}).items():out[i]=add(out.get(i,(0,0)),mul(d,w))
    return out


def solve(rows, n, regularization=.3):
    """Conjugate gradient on regularized least squares, without numpy."""
    rhs=[0.0]*n
    for a,b in rows:
        for i,v in a.items():rhs[i]+=v*b
    def product(x):
        y=[regularization*v for v in x]
        for a,_ in rows:
            ax=sum(v*x[i] for i,v in a.items())
            for i,v in a.items(): y[i]+=v*ax
        return y
    x=[0.0]*n;r=rhs[:];p=r[:];rr=sum(v*v for v in r)
    for _ in range(min(150,n*3)):
        if rr<1e-12: break
        ap=product(p);den=sum(a*b for a,b in zip(p,ap))
        if den<1e-15:break
        alpha=rr/den
        x=[a+alpha*b for a,b in zip(x,p)];r=[a-alpha*b for a,b in zip(r,ap)]
        new=sum(v*v for v in r);beta=new/rr
        p=[a+beta*b for a,b in zip(r,p)];rr=new
    return x


def correct(glyph, model, amount=1.0):
    original=glyph['paths']; upm=model['upm']
    report={'changed':False,'reason':'No confident curve correction.','measurements':0}
    if not math.isfinite(amount) or not 0<=amount<=1:raise ValueError('Amount must be between zero and one.')
    if amount==0:return copy.deepcopy(original),report
    try:ss,obs=observations(original,upm)
    except ValueError as e:report['reason']=str(e);return copy.deepcopy(original),report
    before_edges=mesh(ss)
    if crossing_count(before_edges):report['reason']='Intersecting contours left unchanged.';return copy.deepcopy(original),report
    effects,limits=variables(original,ss)
    rows=[]; checks=[]
    for o in obs:
        target=target_for(o,glyph['group'],model)
        if target is None:continue
        a=basis(ss[o['s']],o['t'],effects);b=basis(ss[o['other']],o['u'],effects)
        coeff={i:dot(sub(b.get(i,(0,0)),a.get(i,(0,0))),o['n']) for i in set(a)|set(b)}
        if not coeff:continue
        delta=target-o['width']
        rows.append((coeff,delta));checks.append((o,target))
    changes=[abs(t-o['width']) for o,t in checks]
    report['measurements']=sum(d>upm*.0005 for d in changes)
    if not changes or max(changes)<upm*.0005:return copy.deepcopy(original),report
    v=solve(rows,len(limits))
    # Scale the whole solution together to preserve the fitted relationships.
    scale=1.0
    for value,lim in zip(v,limits):
        limit=min(upm*.012,lim) if lim is not None else upm*.012
        if abs(value)>limit:scale=min(scale,limit/abs(value))
    before=sum((o['width']-t)**2 for o,t in checks)
    for backoff in (1,.5,.25,.125):
        factor=amount*scale*backoff
        result=copy.deepcopy(original)
        for (pi,ni),mapping in effects.items():
            shift=(sum(d[0]*v[i]*factor for i,d in mapping.items()),sum(d[1]*v[i]*factor for i,d in mapping.items()))
            result[pi]['nodes'][ni]['x']+=shift[0];result[pi]['nodes'][ni]['y']+=shift[1]
        new_ss=segments(result)
        after=sum((dot(sub(evaluate(new_ss[o['other']],o['u']),evaluate(new_ss[o['s']],o['t'])),o['n'])-t)**2 for o,t in checks)
        if after>=before*.99 or crossing_count(mesh(new_ss)):continue
        # Independent remeasurement must improve too, with no loss of paired edges.
        _,new_obs=observations(result,upm)
        lookup={(o['s'],o['t'],o['other']):o for o in new_obs}
        if any((o['s'],o['t'],o['other']) not in lookup for o,_ in checks):continue
        measured=sum((lookup[(o['s'],o['t'],o['other'])]['width']-t)**2 for o,t in checks)
        if measured>=before*.99:continue
        report.update(changed=True,reason='Curve correction preview.',before_error=math.sqrt(before/len(checks)),after_error=math.sqrt(measured/len(checks)))
        return result,report
    report['reason']='Correction did not pass geometry checks.'
    return copy.deepcopy(original),report
