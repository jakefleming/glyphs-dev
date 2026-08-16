# MenuTitle: Tidy Redundant Points
# -*- coding: utf-8 -*-
__doc__ = """
Adds nodes at extremes, then removes on-curve points that don't earn their
keep: any smooth, non-extreme point whose two curve segments can be merged
into one cubic without moving the outline more than a tolerance. Corners,
extremes, and anything whose removal would visibly change the curve are kept.
Runs on selected layers; original goes to the background.
"""

import math
from Foundation import NSPoint
from GlyphsApp import Glyphs, GSPath, LINE, CURVE, OFFCURVE

TOL = 1.5        # units: max outline deviation a removal may cause
AXIS_TOL = 3.0   # deg: tangents this close to h/v mark an extreme -> keep
SMOOTH_TOL = 3.0 # deg: kink bigger than this is a corner -> keep


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def norm(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l) if l > 1e-9 else None


def bez(p0, p1, p2, p3, t):
    mt = 1 - t
    return (
        mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
        mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1],
    )


def angdiff(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


def axis_angle(v):
    return math.degrees(math.atan2(v[1], v[0])) % 180


def fit_cubic(samples, p0, p3, t1, t2):
    """Least-squares cubic through samples with fixed endpoints/tangents.
    t1 points forward from p0, t2 points backward from p3."""
    us = [0.0]
    for a, b in zip(samples, samples[1:]):
        us.append(us[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = us[-1] or 1.0
    us = [u / total for u in us]
    C00 = C01 = C11 = X0 = X1 = 0.0
    for pt, u in zip(samples, us):
        mt = 1 - u
        b1, b2 = 3 * mt * mt * u, 3 * mt * u * u
        a1 = (t1[0] * b1, t1[1] * b1)
        a2 = (t2[0] * b2, t2[1] * b2)
        base = (p0[0] * (mt**3 + b1) + p3[0] * (b2 + u**3),
                p0[1] * (mt**3 + b1) + p3[1] * (b2 + u**3))
        tmp = (pt[0] - base[0], pt[1] - base[1])
        C00 += a1[0] * a1[0] + a1[1] * a1[1]
        C01 += a1[0] * a2[0] + a1[1] * a2[1]
        C11 += a2[0] * a2[0] + a2[1] * a2[1]
        X0 += a1[0] * tmp[0] + a1[1] * tmp[1]
        X1 += a2[0] * tmp[0] + a2[1] * tmp[1]
    det = C00 * C11 - C01 * C01
    chord = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    if abs(det) < 1e-9:
        al1 = al2 = chord / 3.0
    else:
        al1 = (X0 * C11 - X1 * C01) / det
        al2 = (C00 * X1 - C01 * X0) / det
    if al1 <= 0 or al2 <= 0 or al1 > 2 * chord or al2 > 2 * chord:
        return None
    h1 = (p0[0] + t1[0] * al1, p0[1] + t1[1] * al1)
    h2 = (p3[0] + t2[0] * al2, p3[1] + t2[1] * al2)
    return h1, h2


def try_remove(path, i):
    """Try merging the two curve segments meeting at on-curve node i.
    Returns True if the node was removed within tolerance."""
    nodes = list(path.nodes)
    cnt = len(nodes)
    n = nodes[i]
    b1, b2, p3n = nodes[(i + 1) % cnt], nodes[(i + 2) % cnt], nodes[(i + 3) % cnt]
    a2, a1, p0n = nodes[(i - 1) % cnt], nodes[(i - 2) % cnt], nodes[(i - 3) % cnt]
    if (a1.type != OFFCURVE or a2.type != OFFCURVE or b1.type != OFFCURVE
            or b2.type != OFFCURVE or p0n.type == OFFCURVE or p3n.type == OFFCURVE):
        return False

    P = (n.position.x, n.position.y)
    p0 = (p0n.position.x, p0n.position.y)
    p3 = (p3n.position.x, p3n.position.y)
    A1 = (a1.position.x, a1.position.y)
    A2 = (a2.position.x, a2.position.y)
    B1 = (b1.position.x, b1.position.y)
    B2 = (b2.position.x, b2.position.y)

    t_in = norm(sub(P, A2)) or norm(sub(P, A1))
    t_out = norm(sub(B1, P)) or norm(sub(B2, P))
    if t_in is None or t_out is None:
        return False
    # corners stay
    if angdiff(axis_angle(t_in), axis_angle(t_out)) > SMOOTH_TOL:
        return False
    # extremes stay (tangent on axis)
    avg = norm((t_in[0] + t_out[0], t_in[1] + t_out[1])) or t_in
    a = axis_angle(avg)
    if angdiff(a, 0) <= AXIS_TOL or angdiff(a, 90) <= AXIS_TOL:
        return False

    t1 = norm(sub(A1, p0)) or norm(sub(P, p0))
    t2 = norm(sub(B2, p3)) or norm(sub(P, p3))
    if t1 is None or t2 is None:
        return False

    # sample the original pair of segments
    samples = [bez(p0, A1, A2, P, k / 24.0) for k in range(25)]
    samples += [bez(P, B1, B2, p3, k / 24.0) for k in range(1, 25)]

    fit = fit_cubic(samples, p0, p3, t1, t2)
    if fit is None:
        return False
    h1, h2 = fit
    dense = [bez(p0, h1, h2, p3, k / 100.0) for k in range(101)]
    err = 0.0
    for s in samples:
        best = min((s[0] - d[0]) ** 2 + (s[1] - d[1]) ** 2 for d in dense)
        err = max(err, best)
        if err > TOL * TOL:
            return False

    # accept: drop a2, n, b1; retarget surviving handles
    a1.position = NSPoint(h1[0], h1[1])
    b2.position = NSPoint(h2[0], h2[1])
    path.nodes.remove(a2)
    path.nodes.remove(n)
    path.nodes.remove(b1)
    return True


def drop_collinear_line(path, i):
    nodes = list(path.nodes)
    cnt = len(nodes)
    n = nodes[i]
    prev, nxt = nodes[(i - 1) % cnt], nodes[(i + 1) % cnt]
    if n.type != LINE or prev.type == OFFCURVE or nxt.type != LINE:
        return False
    if not path.closed and (i == 0 or i == cnt - 1):
        return False
    a, b, p = prev.position, nxt.position, n.position
    d = norm((b.x - a.x, b.y - a.y))
    if d is None:
        return False
    rel = (p.x - a.x, p.y - a.y)
    perp = abs(rel[0] * d[1] - rel[1] * d[0])
    if perp > TOL:
        return False
    path.nodes.remove(n)
    return True


font = Glyphs.font
font.disableUpdateInterface()
try:
    for layer in font.selectedLayers:
        glyph = layer.parent
        glyph.beginUndo()
        layer.setBackground_(layer)
        try:
            layer.addNodesAtExtremes()
        except Exception:
            pass
        removed = 0
        for path in layer.shapes:
            if not isinstance(path, GSPath):
                continue
            changed = True
            while changed:
                changed = False
                nodes = list(path.nodes)
                if len(nodes) < 7:
                    break
                for i, n in enumerate(nodes):
                    if n.type == OFFCURVE:
                        continue
                    if n.type == CURVE and try_remove(path, i):
                        removed += 1
                        changed = True
                        break
                    if drop_collinear_line(path, i):
                        removed += 1
                        changed = True
                        break
        glyph.endUndo()
        print("%s: removed %d redundant point(s) (original in background)" % (glyph.name, removed))
finally:
    font.enableUpdateInterface()
    Glyphs.redraw()
