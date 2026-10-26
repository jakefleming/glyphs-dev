"""Synthetic geometry and parameter tests for Curse; no Glyphs installation needed."""
import sys, os, json, math, types, unittest
from pathlib import Path
PLUGIN = str(Path(__file__).resolve().parents[1] / 'Curse.glyphsFilter/Contents/Resources/plugin.py')
if os.environ.get('CURSE_TEST_PLUGIN'):
    PLUGIN = os.environ['CURSE_TEST_PLUGIN']
# ---------------------------------------------------------------- stubs
objc = types.ModuleType("objc"); objc.python_method = lambda f: f; sys.modules["objc"] = objc
appkit = types.ModuleType("AppKit")
for name in ("NSView", "NSSlider", "NSTextField", "NSButton", "NSFont", "NSPopover", "NSViewController", "NSEvent"):
    setattr(appkit, name, type(name, (object,), {}))
appkit.NSMakeRect = lambda x, y, w, h: (x, y, w, h)
sys.modules["AppKit"] = appkit
class _Pt(object):
    def __init__(self, x, y): self.x, self.y = x, y
foundation = types.ModuleType("Foundation"); foundation.NSMakePoint = lambda x, y: _Pt(x, y)
sys.modules["Foundation"] = foundation
LINE, CURVE, OFFCURVE = "line", "curve", "offcurve"
class GSNode(object):
    def __init__(self, pos, t): self.position, self.type, self.smooth = pos, t, False
class GSPath(object):
    def __init__(self): self.nodes, self.closed = [], True
ga = types.ModuleType("GlyphsApp"); ga.Glyphs = types.SimpleNamespace(font=None)
ga.GSPath, ga.LINE, ga.CURVE, ga.OFFCURVE = GSPath, LINE, CURVE, OFFCURVE
sys.modules["GlyphsApp"] = ga
pl = types.ModuleType("GlyphsApp.plugins"); pl.FilterWithDialog = type("F", (object,), {}); sys.modules["GlyphsApp.plugins"] = pl

ns = {}; exec(compile(open(PLUGIN).read(), PLUGIN, "exec"), ns)
mi = object.__new__(ns["MakeItalic"])
_bez, _bezD, _unit = ns["_bez"], ns["_bezD"], ns["_unit"]

# ---------------------------------------------------------------- geometry
def flat(nodes, n=24):
    cnt = len(nodes); pts = []
    for i, nd in enumerate(nodes):
        if nd[2] == 'offcurve': continue
        h2, h1, p0 = nodes[(i-1) % cnt], nodes[(i-2) % cnt], nodes[(i-3) % cnt]
        if h1[2] == 'offcurve' and h2[2] == 'offcurve':
            C = ((p0[0], p0[1]), (h1[0], h1[1]), (h2[0], h2[1]), (nd[0], nd[1]))
            for j in range(n): pts.append(_bez(C, j / n))
        else:
            p0 = nodes[(i-1) % cnt]
            for j in range(n): pts.append((p0[0] + (nd[0]-p0[0]) * j / n, p0[1] + (nd[1]-p0[1]) * j / n))
    return pts

def segd(P, a, b):
    vx, vy = b[0]-a[0], b[1]-a[1]; L2 = vx*vx + vy*vy
    if L2 < 1e-12: return math.hypot(P[0]-a[0], P[1]-a[1])
    t = max(0, min(1, ((P[0]-a[0])*vx + (P[1]-a[1])*vy) / L2))
    return math.hypot(P[0]-a[0]-t*vx, P[1]-a[1]-t*vy)

def odist(A, B):
    ds = []
    for pa, pb in zip(A, B):
        fb = flat(pb)
        for P in flat(pa): ds.append(min(segd(P, fb[i], fb[(i+1) % len(fb)]) for i in range(len(fb))))
    ds.sort()
    return sum(ds)/len(ds), ds[int(len(ds)*.9)], ds[-1]

def sanity(paths):
    """Shape invariants: kinks at smooth nodes, crossed handles, curvature-sign
    flips within a segment (new inflections), tiny/negative-length handles."""
    kinks = crossings = flips = 0
    for nodes in paths:
        cnt = len(nodes)
        for i, nd in enumerate(nodes):
            if nd[2] == 'offcurve': continue
            a, b = nodes[(i-1) % cnt], nodes[(i+1) % cnt]
            if a[2] == 'offcurve' and b[2] == 'offcurve' and len(nd) > 3 and nd[3]:
                v1 = _unit(nd[0]-a[0], nd[1]-a[1]); v2 = _unit(b[0]-nd[0], b[1]-nd[1])
                if v1 and v2:
                    ang = math.degrees(math.acos(max(-1, min(1, v1[0]*v2[0] + v1[1]*v2[1]))))
                    if ang > 3.0: kinks += 1
            h1, h2, p3 = nodes[(i+1) % cnt], nodes[(i+2) % cnt], nodes[(i+3) % cnt]
            if h1[2] == 'offcurve' and h2[2] == 'offcurve':
                C = ((nd[0], nd[1]), (h1[0], h1[1]), (h2[0], h2[1]), (p3[0], p3[1]))
                # crossed handles: control polygon self-intersects
                def cross(o, a, b): return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
                s1 = cross(C[0], C[1], C[2]); s2 = cross(C[1], C[2], C[3])
                if s1 * s2 < 0 and abs(s1) > 1 and abs(s2) > 1:
                    # possible loop; check tangent turn > 180 as a proxy
                    t0 = _unit(C[1][0]-C[0][0], C[1][1]-C[0][1]); t1 = _unit(C[3][0]-C[2][0], C[3][1]-C[2][1])
                    if t0 and t1 and (t0[0]*t1[0] + t0[1]*t1[1]) < -0.2: crossings += 1
                # curvature sign flip
                signs = []
                for k in range(1, 12):
                    t = k/12.0; d = _bezD(C, t)
                    mt = 1-t
                    dd = (6*(mt*(C[2][0]-2*C[1][0]+C[0][0]) + t*(C[3][0]-2*C[2][0]+C[1][0])),
                          6*(mt*(C[2][1]-2*C[1][1]+C[0][1]) + t*(C[3][1]-2*C[2][1]+C[1][1])))
                    c = d[0]*dd[1] - d[1]*dd[0]
                    if abs(c) > 1e-6: signs.append(1 if c > 0 else -1)
                if signs and min(signs) != max(signs): flips += 1
    return {"kinks": kinks, "crossings": crossings, "flips": flips}

class Master(object):
    def __init__(self, xh): self.xHeight = xh; self.verticalStems = [100]
class Layer(object):
    def __init__(self, shapes, xh): self.shapes = shapes; self.anchors = []; self._m = Master(xh)
    def associatedFontMaster(self): return self._m

def build(P):
    out = []
    for nodes in P:
        p = GSPath()
        for x, y, t, sm in nodes:
            n = GSNode(_Pt(x, y), t); n.smooth = bool(sm); p.nodes.append(n)
        out.append(p)
    return out

def ellipse(cx=300, cy=250, rx=250, ry=250, reverse=False):
    k = .5522847498307936
    p = [(cx+rx,cy,'curve',True),(cx+rx,cy+k*ry,'offcurve',False),
         (cx+k*rx,cy+ry,'offcurve',False),(cx,cy+ry,'curve',True),
         (cx-k*rx,cy+ry,'offcurve',False),(cx-rx,cy+k*ry,'offcurve',False),
         (cx-rx,cy,'curve',True),(cx-rx,cy-k*ry,'offcurve',False),
         (cx-k*rx,cy-ry,'offcurve',False),(cx,cy-ry,'curve',True),
         (cx+k*rx,cy-ry,'offcurve',False),(cx+rx,cy-k*ry,'offcurve',False)]
    return list(reversed(p)) if reverse else p

def ring():
    return [ellipse(),ellipse(rx=170,ry=170,reverse=True)]

def polygon(points):
    return [(x,y,'line',False) for x,y in points]

def output(layer):
    return [[(n.position.x,n.position.y,n.type,bool(n.smooth)) for n in p.nodes] for p in layer.shapes]

def transform(paths, angle=12, curve=1, term=0, diag=1, stem=0, extremes=False):
    layer=Layer(build(paths),500)
    layer.width=600
    mi.italicize(layer,angle,curve,term,diag,stem,extremes)
    return output(layer)

class GeometryTests(unittest.TestCase):
    def test_subcurve_matches_original_parameterization(self):
        cubic=((0.,0.),(30.,170.),(180.,-50.),(240.,100.))
        for start,end in [(0.,1.),(.2,.8),(1.,2.),(1.,0.),(1.,1.),
                          (1.-1e-14,1.5),(-2.,.5),(2.,-1.)]:
            with self.subTest(interval=(start,end)):
                part=ns['_sub'](cubic,start,end)
                for t in (0.,.1,.37,.5,.81,1.):
                    self.assertLess(math.dist(_bez(part,t),_bez(cubic,start+t*(end-start))),1e-8)
    def test_extension_keeps_endpoint_tangent(self):
        cubic=((0.,0.),(30.,170.),(180.,-50.),(240.,100.))
        extended=ns['_sub'](cubic,1.,2.)
        self.assertEqual(extended[0],cubic[-1])
        self.assertGreater(math.dist(extended[0],extended[1]),1.)
        self.assertLess(math.dist(_bezD(extended,0.),_bezD(cubic,1.)),1e-9)
    def test_subcurve_reversal_and_composition(self):
        cubic=((0.,0.),(30.,170.),(180.,-50.),(240.,100.))
        backward=ns['_sub'](cubic,1.,0.)
        for a,b in zip(backward,reversed(cubic)):
            self.assertLess(math.dist(a,b),1e-9)
        expanded=ns['_sub'](cubic,-1.,2.)
        recovered=ns['_sub'](expanded,1/3.,2/3.)
        for a,b in zip(recovered,cubic):
            self.assertLess(math.dist(a,b),1e-8)

    def test_zero_angle_is_exact(self):
        p=ring(); self.assertEqual(p,transform(p,angle=0,extremes=True))
    def test_zero_corrections_is_exact_shear(self):
        p=ring(); out=transform(p,curve=0,diag=0)
        for a,b in zip(p,out):
            for x,y in zip(a,b):
                self.assertAlmostEqual(y[0],x[0]+(x[1]-250)*math.tan(math.radians(12)))
                self.assertEqual(y[1:],x[1:])
    def test_ring_preserves_topology_and_smoothness(self):
        p=ring()
        for angle in (-30,-12,12,30):
            out=transform(p,angle=angle)
            self.assertEqual([[n[2:] for n in x] for x in p],[[n[2:] for n in x] for x in out])
            self.assertEqual(sanity(out),dict(kinks=0,crossings=0,flips=0))
    def test_horizontal_extrema_height_stays(self):
        p=ring(); out=transform(p)
        for a,b in zip(p,out):
            for n,q in zip(a,b):
                if n[2]!='offcurve' and n[1] in (0,80,420,500):self.assertEqual(n[1],q[1])
    def test_negative_angle_mirrors_positive(self):
        p=ring(); mirror=lambda ps:[[(600-n[0],n[1],n[2],n[3]) for n in path] for path in ps]
        a=mirror(transform(p,angle=12));b=transform(mirror(p),angle=-12)
        for pa,pb in zip(a,b):
            for x,y in zip(pa,pb):self.assertLess(math.dist(x[:2],y[:2]),1e-7)
    def test_extrema_refit_has_vertical_handles(self):
        out=transform(ring(),extremes=True)
        for path in out:
            self.assertTrue(any(n[2]=='curve' and abs(path[(i-1)%len(path)][0]-n[0])<1e-6 and abs(path[(i+1)%len(path)][0]-n[0])<1e-6 for i,n in enumerate(path)))
        self.assertEqual(sanity(out)['kinks'],0)
    def test_straight_stem_perpendicular_weight(self):
        p=[polygon([(260,0),(340,0),(340,700),(260,700)])]
        out=transform(p,curve=0,diag=0,stem=1)[0]
        a,b=out[0],out[1];t=(math.sin(math.radians(12)),math.cos(math.radians(12)))
        width=abs((b[0]-a[0])*t[1]-(b[1]-a[1])*t[0])
        self.assertAlmostEqual(width,80,places=6)
    def test_diagonal_perpendicular_weight(self):
        d=math.sqrt(2);p=[polygon([(0,0),(50/d,-50/d),(500+50/d,500-50/d),(500,500)])]
        out=transform(p,curve=0,diag=1)[0]
        a,b,c=out[:3];t=_unit(c[0]-b[0],c[1]-b[1]);w=abs((b[0]-a[0])*t[1]-(b[1]-a[1])*t[0])
        self.assertAlmostEqual(w,50,places=6)
    def test_nonfinite_rejected_before_mutation(self):
        for value in (float('nan'),float('inf'),90):
            layer=Layer(build(ring()),500);before=output(layer)
            with self.assertRaises(ValueError):mi.italicize(layer,value,1,0,1,0,False)
            self.assertEqual(before,output(layer))
    def test_components_rejected_before_mutation(self):
        layer=Layer(build(ring()),500); layer.shapes.append(object())
        before=layer.shapes[0].nodes[0].position.x
        with self.assertRaises(ValueError):mi.italicize(layer,12,1,0,1,0,False)
        self.assertEqual(before,layer.shapes[0].nodes[0].position.x)
    def test_export_has_no_dialog_dependency(self):
        layer=Layer(build(ring()),500)
        mi.filter(layer,False,{'angle':-12,'curve':100,'diagonal':100,'extremes':'false'})
        self.assertEqual(output(layer),transform(ring(),angle=-12))
    def test_export_invalid_fails_loudly(self):
        with self.assertRaises(ValueError):mi.filter(Layer(build(ring()),500),False,{'angle':'nan'})
    def test_anchors_follow_shear(self):
        layer=Layer(build(ring()),500); layer.anchors=[types.SimpleNamespace(position=_Pt(300,500))]
        mi.italicize(layer,12,1,0,1,0,False)
        self.assertAlmostEqual(layer.anchors[0].position.x,300+250*math.tan(math.radians(12)))
    def test_open_contour_only_shears(self):
        layer=Layer(build([ellipse()]),500); layer.shapes[0].closed=False
        before=output(layer)
        mi.italicize(layer,12,1,0,1,0,True)
        for a,b in zip(before[0],output(layer)[0]):self.assertAlmostEqual(b[0],a[0]+(a[1]-250)*math.tan(math.radians(12)))


class ContourGuardTests(unittest.TestCase):
    def guard(self, before, after):
        return ns['_safe_contours'](
            [[n[:2] for n in c] for c in before],
            [[n[:2] for n in c] for c in after],
            [[n[2] for n in c] for c in before],
            [[n[3] for n in c] for c in before])

    def test_valid_correction_is_not_reduced(self):
        before=ring()
        after=[[(x*1.05,y,t,s) for x,y,t,s in c] for c in before]
        safe,amount=self.guard(before,after)
        self.assertEqual(amount,1.)
        self.assertEqual(safe,[[n[:2] for n in c] for c in after])

    def test_crossed_contour_backs_off(self):
        before=[polygon([(0,0),(100,0),(100,100),(0,100)])]
        after=[polygon([(0,0),(100,100),(100,0),(0,100)])]
        safe,amount=self.guard(before,after)
        self.assertLess(amount,1.)
        self.assertGreater(amount,0.)
        self.assertEqual(ns['_outline_crossings'](safe),0)
        self.assertEqual(ns['_outline_signature'](safe),ns['_outline_signature']([[n[:2] for n in before[0]]]))

    def test_counter_cannot_leave_outer_contour(self):
        before=ring();after=[before[0],[(x+500,y,t,s) for x,y,t,s in before[1]]]
        safe,amount=self.guard(before,after)
        self.assertLess(amount,1.)
        flat=[ns['_outline_points'](c,[n[2] for n in src],.005) for c,src in zip(safe,before)]
        original=[ns['_outline_points']([n[:2] for n in c],[n[2] for n in c],.005) for c in before]
        self.assertEqual(ns['_outline_crossings'](flat),0)
        self.assertEqual(ns['_outline_signature'](flat),ns['_outline_signature'](original))

    def test_adjacent_edges_are_not_intersections(self):
        self.assertEqual(ns['_outline_crossings']([[(0,0),(100,0),(100,100),(0,100)]]),0)
        self.assertEqual(ns['_outline_crossings']([[(0,0),(100,100),(100,0),(0,100)]]),1)

    def test_signed_control_extremes_stay_smooth(self):
        for angle in (-45,-24,24,45):
            for term,stem in ((0,0),(1,1),(.5,1.5)):
                out=transform(ring(),angle=angle,curve=1.5,term=term,stem=stem,diag=1.5)
                self.assertEqual(sanity(out)['kinks'],0)
                flat=[ns['_outline_points']([n[:2] for n in c],[n[2] for n in c],.005) for c in out]
                self.assertEqual(ns['_outline_crossings'](flat),0)

    def test_smooth_join_handles_are_collinear(self):
        p=ellipse();before=[n[:2] for n in p];changed=list(before)
        changed[1]=(changed[1][0]+15,changed[1][1])
        safe=ns['_smooth_points'](changed,before,[n[2] for n in p],[n[3] for n in p])
        a,b,c=safe[-1],safe[0],safe[1]
        v,w=_unit(b[0]-a[0],b[1]-a[1]),_unit(c[0]-b[0],c[1]-b[1])
        self.assertLess(math.dist(v,w),1e-9)

if __name__=='__main__':unittest.main()
