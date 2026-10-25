"""Curse regression harness (run with plain python3, no Glyphs needed).

Fixtures live in ../fixtures/makeitalic/<name>.json:
    {"paths": [[x, y, type, smooth], ...], "xHeight": ..,
     "italify": [[x, y, type, smooth], ...] or null,
     "settings": {"angle":12, "curve":.., "terminals":.., "diagonal":.., "stem":.., "extremes":bool},
     "metric": "italify" | "sanity"}

  metric "italify": mean outline distance to the Italify reference must not grow.
  metric "sanity" : shape invariants (kinks, handle crossings, curvature flips,
                    node counts) must not get worse than the baseline.

Usage:
    python3 _makeitalic_harness.py            # report vs baseline
    python3 _makeitalic_harness.py --accept   # write current numbers as the new baseline
"""
import sys, os, json, math, types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(HERE, "..", "Plugins", "Curse.glyphsFilter", "Contents", "Resources", "plugin.py")
FIXDIR = os.path.join(HERE, "..", "fixtures", "makeitalic")
BASELINE = os.path.join(FIXDIR, "_baseline.json")

# ---------------------------------------------------------------- stubs
objc = types.ModuleType("objc"); objc.python_method = lambda f: f; sys.modules["objc"] = objc
appkit = types.ModuleType("AppKit")
for name in ("NSView", "NSSlider", "NSTextField", "NSButton", "NSFont"):
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

# ---------------------------------------------------------------- run
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

def run_fixture(fx):
    st = fx.get("settings", {})
    Lo = Layer(build(fx["paths"]), fx["xHeight"])
    mi.italicize(Lo, st.get("angle", 12.0), st.get("curve", 100)/100.0, st.get("terminals", 0)/100.0,
                 st.get("diagonal", 100)/100.0, st.get("stem", 0)/100.0, bool(st.get("extremes", False)))
    return [[(n.position.x, n.position.y, n.type, bool(n.smooth)) for n in p.nodes] for p in Lo.shapes]

def main():
    accept = "--accept" in sys.argv
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    new = {}
    fails = 0
    for fn in sorted(os.listdir(FIXDIR)):
        if not fn.endswith(".json") or fn.startswith("_"): continue
        fx = json.load(open(os.path.join(FIXDIR, fn)))
        name = fn[:-5]
        out = run_fixture(fx)
        rec = {"sanity": sanity(out), "sanity_upright": sanity(fx["paths"])}
        if fx.get("italify"):
            rec["italify_dist"] = odist(out, fx["italify"])
        new[name] = rec
        b = base.get(name)
        metric = fx.get("metric", "italify" if fx.get("italify") else "sanity")
        status = "new"
        if b:
            status = "ok"
            if metric == "italify" and "italify_dist" in rec and rec["italify_dist"][0] > b["italify_dist"][0] + 0.05:
                status = "REGRESSED (italify %.2f -> %.2f)" % (b["italify_dist"][0], rec["italify_dist"][0]); fails += 1
            for key in ("kinks", "crossings", "flips"):
                if rec["sanity"][key] > b["sanity"][key]:
                    status = "REGRESSED (%s %d -> %d)" % (key, b["sanity"][key], rec["sanity"][key]); fails += 1
        it = ("italify mean %.2f p90 %.2f max %.2f" % rec["italify_dist"]) if "italify_dist" in rec else "no italify ref"
        s = rec["sanity"]; su = rec["sanity_upright"]
        print("%-10s [%-7s] %s | kinks %d(%d) cross %d(%d) flips %d(%d) | %s" % (
            name, metric, it, s["kinks"], su["kinks"], s["crossings"], su["crossings"], s["flips"], su["flips"], status))
    if accept:
        json.dump(new, open(BASELINE, "w"), indent=1)
        print("baseline written")
    elif fails:
        print("%d REGRESSION(S)" % fails)
        sys.exit(1)

if __name__ == "__main__":
    main()
