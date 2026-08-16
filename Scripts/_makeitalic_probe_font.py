# Builds a probe font with synthetic glyphs for black-box testing Italify.
# Run inside Glyphs' Macro panel.
import math
from GlyphsApp import Glyphs, GSFont, GSGlyph, GSPath, GSNode, LINE, CURVE, OFFCURVE
from Foundation import NSPoint

font = GSFont()
font.familyName = "ItalifyProbe"
m = font.masters[0]
m.xHeight = 500
m.capHeight = 700
m.ascender = 750
m.descender = -250
Glyphs.fonts.append(font)

KAPPA = 0.5522847498

def node(x, y, t=LINE, smooth=False):
    n = GSNode(NSPoint(x, y), t)
    n.smooth = smooth
    return n

def circle(cx, cy, r, ccw=True):
    """4-node circle, extremes only, ends on an on-curve node."""
    p = GSPath()
    quads = [(1, 0), (0, 1), (-1, 0), (0, -1)] if ccw else [(1, 0), (0, -1), (-1, 0), (0, 1)]
    seq = []
    for i in range(4):
        ax, ay = quads[i]
        bx, by = quads[(i + 1) % 4]
        A = (cx + r * ax, cy + r * ay)
        h1 = (A[0] + r * KAPPA * bx, A[1] + r * KAPPA * by)
        B = (cx + r * bx, cy + r * by)
        h2 = (B[0] + r * KAPPA * ax, B[1] + r * KAPPA * ay)
        seq += [node(*A, t=CURVE, smooth=True), node(*h1, t=OFFCURVE), node(*h2, t=OFFCURVE)]
    seq = seq[1:] + seq[:1]  # off, off, on, ... ends with an on-curve
    for n in seq:
        p.nodes.append(n)
    p.closed = True
    return p

def poly(pts):
    p = GSPath()
    for x, y in pts:
        p.nodes.append(node(x, y))
    p.closed = True
    return p

def bar(c0, c1, hw):
    ux, uy = c1[0] - c0[0], c1[1] - c0[1]
    L = math.hypot(ux, uy)
    ux, uy = ux / L, uy / L
    nx, ny = -uy, ux
    pts = [(c0[0] + nx * hw, c0[1] + ny * hw), (c0[0] - nx * hw, c0[1] - ny * hw),
           (c1[0] - nx * hw, c1[1] - ny * hw), (c1[0] + nx * hw, c1[1] + ny * hw)]
    a = 0
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        a += x1 * y2 - x2 * y1
    if a < 0:
        pts.reverse()
    return poly(pts)

def add(name, paths, width=600):
    g = GSGlyph(name)
    font.glyphs.append(g)
    layer = g.layers[m.id]
    layer.width = width
    for p in paths:
        layer.shapes.append(p)
    return g

# 1. monoline ring o: outer r=250 CCW, inner r=170 CW  (stroke 80)
add("o", [circle(300, 250, 250, True), circle(300, 250, 170, False)])
# 2. v: two diagonal bars
add("v", [bar((80, 500), (300, 0), 40), bar((300, 0), (520, 500), 40)])
# 3. vertical stem, flat caps
add("l", [poly([(260, 0), (340, 0), (340, 700), (260, 700)])])
# 4. horizontal bar
add("hbar", [poly([(50, 210), (550, 210), (550, 290), (50, 290)])])
# 5. n-like: stem + arch (single outline, smooth join)  built as stem rect + half ring merged crudely as separate paths
add("n", [poly([(60, 0), (140, 0), (140, 500), (60, 500)]),
          # arch: outer semicircle r=180 centred (300,320) top half, inner r=100, plus right stem
          ])
# 6. round-terminal stroke: vertical stem with semicircular bottom cap, flat top
p = GSPath()
cx, r, top, y = 300.0, 40.0, 600.0, 200.0
KA = KAPPA * r
seq = [node(cx + r, top), node(cx + r, y, LINE, True),
       node(cx + r, y - KA, OFFCURVE), node(cx + KA, y - r, OFFCURVE), node(cx, y - r, CURVE, True),
       node(cx - KA, y - r, OFFCURVE), node(cx - r, y - KA, OFFCURVE), node(cx - r, y, CURVE, True),
       node(cx - r, top)]
for n in seq:
    p.nodes.append(n)
p.closed = True
add("term", [p])
# 7. quarter-arc bracket: an L-shape with a rounded inner+outer corner (tests one arc segment in isolation)
p = GSPath()
R, w = 200.0, 80.0  # outer radius, stroke
seq = [node(100, 600), node(100, 100 + R, LINE, True),
       node(100, 100 + R - R * KAPPA, OFFCURVE), node(100 + R - R * KAPPA, 100, OFFCURVE), node(100 + R, 100, CURVE, True),
       node(600, 100), node(600, 100 + w),
       node(100 + R, 100 + w, LINE, True),
       node(100 + w + (R - w) * (1 - KAPPA), 100 + w, OFFCURVE), node(100 + w, 100 + w + (R - w) * (1 - KAPPA), OFFCURVE),
       node(100 + w, 100 + R, CURVE, True),
       node(100 + w, 600)]
for n in seq:
    p.nodes.append(n)
p.closed = True
add("larc", [p])

font.newTab("/o/v/l/hbar/term/larc")
print("probe font built:", [g.name for g in font.glyphs])
