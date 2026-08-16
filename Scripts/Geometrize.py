# MenuTitle: Geometrize
# -*- coding: utf-8 -*-
__doc__ = """
Rebuilds loosely drawn glyphs as clean geometry. Traces each path, keeps only real
corners and axis extremes, and refits fresh cubic curves between them with exact
h/v tangents at extremes, metric snapping, and uniform tension. Original layer is
copied to the background. Runs on selected layers.
"""

import math
from Foundation import NSPoint
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, CURVE, OFFCURVE

STEP = 3            # units: resampling step along the outline
SMOOTH_PASSES = 30  # de-wobble passes before analysis (~16 units of gaussian blur)
CORNER_TURN = 30    # deg: direction change that counts as a real corner
SOFT_TURN = 45      # deg: turn over ~100 units that earns a smooth apex point
LINE_DEV = 4        # units: max bow for a span to become a straight line
STRAIGHT_W = 120    # units: half-window for the curvature test around an extreme
TURN_MIN = 12       # deg: total direction change below this reads as straight
TURN_CONSIST = 0.6  # 0..1: how one-directional the turning must be to count as a curve
LINE_ANGLE_TOL = 8  # deg: near-h/v lines get snapped exactly h/v
METRIC_TOL = 25     # units: snap distance to vertical metrics
MIN_KEY_DIST = 40   # units: minimum spacing between kept points
FIT_ERR = 15        # units: max fitting error before a curve is subdivided
TENSION = 0.58      # final uniform handle tension (0.55 = circle)

# ---------- small vector helpers ----------

def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1])

def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1])

def vmul(a, s):
    return (a[0] * s, a[1] * s)

def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1]

def vlen(a):
    return math.hypot(a[0], a[1])

def vnorm(a):
    l = vlen(a)
    return (a[0] / l, a[1] / l) if l > 1e-9 else (0.0, 0.0)

def turn_deg(a, b):
    la, lb = vlen(a), vlen(b)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    c = max(-1.0, min(1.0, vdot(a, b) / (la * lb)))
    return math.degrees(math.acos(c))

# ---------- sampling ----------

def bez(p0, p1, p2, p3, t):
    mt = 1 - t
    return (
        mt * mt * mt * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t * t * t * p3[0],
        mt * mt * mt * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t * t * t * p3[1],
    )

def sample_path(path):
    """Dense point trace of a GSPath in node order."""
    nodes = list(path.nodes)
    ons = [i for i, n in enumerate(nodes) if n.type != OFFCURVE]
    if len(ons) < 2:
        return None
    pts = []
    pairs = list(zip(ons, ons[1:] + ([ons[0]] if path.closed else [])))
    for a, b in pairs:
        p0 = (nodes[a].position.x, nodes[a].position.y)
        offs = []
        i = (a + 1) % len(nodes)
        while i != b:
            offs.append((nodes[i].position.x, nodes[i].position.y))
            i = (i + 1) % len(nodes)
        p3 = (nodes[b].position.x, nodes[b].position.y)
        if len(offs) == 2:
            for k in range(30):
                pts.append(bez(p0, offs[0], offs[1], p3, k / 30.0))
        else:
            for k in range(10):
                t = k / 10.0
                pts.append((p0[0] + (p3[0] - p0[0]) * t, p0[1] + (p3[1] - p0[1]) * t))
    if not path.closed:
        last = nodes[ons[-1]].position
        pts.append((last.x, last.y))
    return pts

def resample(pts, closed):
    """Uniform arc-length resampling with step STEP."""
    if closed:
        pts = pts + [pts[0]]
    out = [pts[0]]
    dist_to_next = STEP
    for a, b in zip(pts, pts[1:]):
        seg = vlen(vsub(b, a))
        if seg < 1e-9:
            continue
        d = vnorm(vsub(b, a))
        t = 0.0
        while dist_to_next <= seg - t:
            t += dist_to_next
            out.append(vadd(a, vmul(d, t)))
            dist_to_next = STEP
        dist_to_next -= seg - t
    if closed and vlen(vsub(out[-1], out[0])) < STEP * 0.5:
        out.pop()
    return out

def smooth_poly(pts, closed):
    n = len(pts)
    kernel = (1, 4, 6, 4, 1)
    for _ in range(SMOOTH_PASSES):
        new = []
        for i in range(n):
            sx = sy = sw = 0.0
            for k, w in zip((-2, -1, 0, 1, 2), kernel):
                j = i + k
                if closed:
                    j %= n
                elif j < 0 or j >= n:
                    continue
                sx += pts[j][0] * w
                sy += pts[j][1] * w
                sw += w
            new.append((sx / sw, sy / sw))
        pts = new
    return pts

# ---------- key point detection ----------

def circular_groups(candidates, n):
    """Group circularly-consecutive indices; returns list of index lists."""
    if not candidates:
        return []
    cset = set(candidates)
    groups = []
    used = set()
    for i in sorted(candidates):
        if i in used:
            continue
        grp = [i]
        used.add(i)
        j = (i + 1) % n
        while j in cset and j not in used:
            grp.append(j)
            used.add(j)
            j = (j + 1) % n
        groups.append(grp)
    # merge wrap-around group
    if len(groups) > 1 and groups[0][0] == 0 and groups[-1][-1] == n - 1:
        groups[0] = groups.pop() + groups[0]
    return groups

def detect_corners(sm, closed):
    n = len(sm)
    k = max(3, int(24 / STEP))
    turns = {}
    idx_range = range(n) if closed else range(k, n - k)
    for i in idx_range:
        v1 = vsub(sm[i], sm[(i - k) % n])
        v2 = vsub(sm[(i + k) % n], sm[i])
        t = turn_deg(v1, v2)
        if t >= CORNER_TURN:
            turns[i] = t
    corners = []
    for grp in circular_groups(list(turns.keys()), n):
        corners.append(max(grp, key=lambda i: turns[i]))
    return corners

def signed_turn(a, b):
    """Signed angle (deg) from direction a to direction b."""
    cross = a[0] * b[1] - a[1] * b[0]
    dot = vdot(a, b)
    return math.degrees(math.atan2(cross, dot))


def locally_straight(sm, i, w, n, closed):
    """True when the outline around sample i has no consistent curvature.
    A genuine curve turns steadily in one direction; hand wobble on a
    straight run alternates turn direction and cancels out."""
    # coarse directions across the window: long baselines average out wobble
    K = 8
    idxs = [i - w + (2 * w * k) // K for k in range(K + 1)]
    pts = []
    for j in idxs:
        j = j % n if closed else min(max(j, 0), n - 1)
        pts.append(sm[j])
    dirs = []
    for a, b in zip(pts, pts[1:]):
        v = vsub(b, a)
        if vlen(v) > 1e-9:
            dirs.append(v)
    total = 0.0
    total_abs = 0.0
    for a, b in zip(dirs, dirs[1:]):
        t = signed_turn(a, b)
        total += t
        total_abs += abs(t)
    if abs(total) < TURN_MIN:
        return True
    return abs(total) / (total_abs + 1e-9) < TURN_CONSIST


def detect_soft_turns(sm, closed):
    """Fast-but-rounded turns (too spread out to read as corners): the outline
    swings SOFT_TURN+ degrees across a ~100-unit window. These get their own
    smooth apex point so one cubic doesn't strain around the whole turn."""
    n = len(sm)
    k = max(6, int(48 / STEP))
    turns = {}
    idx_range = range(n) if closed else range(k, n - k)
    for i in idx_range:
        v1 = vsub(sm[i], sm[(i - k) % n])
        v2 = vsub(sm[(i + k) % n], sm[i])
        t = turn_deg(v1, v2)
        if t >= SOFT_TURN:
            turns[i] = t
    return [max(grp, key=lambda i: turns[i]) for grp in circular_groups(list(turns.keys()), n)]


def detect_extremes(sm, closed, corners):
    n = len(sm)
    w = max(4, int(36 / STEP))
    W = max(8, int(STRAIGHT_W / STEP))

    def corner_gap(i):
        if not corners:
            return None
        return min(
            min(abs(i - c), n - abs(i - c)) if closed else abs(i - c)
            for c in corners
        )

    def is_noise(i):
        # clip the straightness window at the nearest corner: a corner's turn
        # must not masquerade as curvature that legitimizes a fake extreme
        # pre-analysis smoothing rounds every corner into ~4 sigma of fake
        # curvature; the window must stop before entering that zone
        corner_zone = int(4 * math.sqrt(SMOOTH_PASSES))
        gap = corner_gap(i)
        hw = W if gap is None else min(W, gap - corner_zone)
        if hw < 6:
            return True  # inside a corner's blur zone: not its own feature
        return locally_straight(sm, i, hw, n, closed)

    found = []
    for axis in (0, 1):
        for mode in (max, min):
            cands = []
            idx_range = range(n) if closed else range(w, n - w)
            for i in idx_range:
                window = [sm[(i + d) % n][axis] for d in range(-w, w + 1)]
                if sm[i][axis] == mode(window) and not is_noise(i):
                    cands.append(i)
            for grp in circular_groups(cands, n):
                mid = grp[len(grp) // 2]
                # extreme in x => vertical tangent; in y => horizontal
                found.append((mid, "v" if axis == 0 else "h"))
    return found

class Key(object):
    def __init__(self, idx, corner=False, axis=None):
        self.idx = idx
        self.corner = corner
        self.axis = axis  # "h"/"v" tangent constraint, or None
        self.pos = None
        self.tangent = None  # forward unit tangent (None for corners)

def collect_keys(sm, closed):
    n = len(sm)
    min_gap = max(2, int(MIN_KEY_DIST / STEP))
    corners = detect_corners(sm, closed)
    keys = [Key(i, corner=True) for i in corners]
    taken = [k.idx for k in keys]

    def far_from_taken(idx):
        if not taken:
            return True
        return min(
            min(abs(idx - t), n - abs(idx - t)) if closed else abs(idx - t)
            for t in taken
        ) >= min_gap

    for idx, axis in detect_extremes(sm, closed, corners):
        if far_from_taken(idx):
            keys.append(Key(idx, axis=axis))
            taken.append(idx)
    # soft turns only fill gaps corners/extremes didn't already anchor
    for idx in detect_soft_turns(sm, closed):
        if far_from_taken(idx):
            keys.append(Key(idx))
            taken.append(idx)
    if not closed:
        for endpoint in (0, n - 1):
            if all(abs(k.idx - endpoint) >= min_gap for k in keys):
                keys.append(Key(endpoint, corner=True))
    keys.sort(key=lambda k: k.idx)
    return keys

def assign_geometry(keys, sm, closed, metrics):
    n = len(sm)
    k2 = max(2, int(15 / STEP))
    real = []
    for key in keys:
        key.pos = sm[key.idx]
        if key.corner:
            real.append(key)
            continue
        a = sm[(key.idx - k2) % n]
        b = sm[(key.idx + k2) % n]
        raw_t = vnorm(vsub(b, a))
        t = raw_t
        if key.axis == "h":
            t = (1.0 if raw_t[0] >= 0 else -1.0, 0.0)
        elif key.axis == "v":
            t = (0.0, 1.0 if raw_t[1] >= 0 else -1.0)
        # a real extreme's outline direction is close to the forced axis;
        # a big disagreement means it was noise on a straight-ish run
        if key.axis and turn_deg(raw_t, t) > 30:
            continue
        key.tangent = t
        real.append(key)
    keys[:] = real
    # snap to vertical metrics (horizontal extremes and corners only)
    for key in keys:
        if key.corner or key.axis == "h":
            for m in metrics:
                if abs(key.pos[1] - m) <= METRIC_TOL:
                    key.pos = (key.pos[0], m)
                    break

# ---------- curve fitting (Schneider, fixed tangents) ----------

def chord_params(sub):
    us = [0.0]
    for a, b in zip(sub, sub[1:]):
        us.append(us[-1] + vlen(vsub(b, a)))
    total = us[-1] or 1.0
    return [u / total for u in us]

def fit_one(sub, t1, t2):
    """Fit one cubic; t1 = outgoing tangent at start, t2 = incoming (points backward from end)."""
    p0, p3 = sub[0], sub[-1]
    us = chord_params(sub)
    C00 = C01 = C11 = X0 = X1 = 0.0
    for pt, u in zip(sub, us):
        mt = 1 - u
        b0, b1, b2, b3 = mt ** 3, 3 * mt * mt * u, 3 * mt * u * u, u ** 3
        a1 = vmul(t1, b1)
        a2 = vmul(t2, b2)
        tmp = vsub(pt, vadd(vmul(p0, b0 + b1), vmul(p3, b2 + b3)))
        C00 += vdot(a1, a1)
        C01 += vdot(a1, a2)
        C11 += vdot(a2, a2)
        X0 += vdot(a1, tmp)
        X1 += vdot(a2, tmp)
    det = C00 * C11 - C01 * C01
    chord = vlen(vsub(p3, p0))
    if abs(det) < 1e-9:
        alpha1 = alpha2 = chord / 3.0
    else:
        alpha1 = (X0 * C11 - X1 * C01) / det
        alpha2 = (C00 * X1 - C01 * X0) / det
    if alpha1 <= 0 or alpha1 > chord * 2 or alpha2 <= 0 or alpha2 > chord * 2:
        alpha1 = alpha2 = chord / 3.0
    h1 = vadd(p0, vmul(t1, alpha1))
    h2 = vadd(p3, vmul(t2, alpha2))
    err, worst = 0.0, len(sub) // 2
    for i, (pt, u) in enumerate(zip(sub, us)):
        e = vlen(vsub(bez(p0, h1, h2, p3, u), pt))
        if e > err:
            err, worst = e, i
    return (h1, h2), err, worst

def fit_span(sub, t1, t2, depth=0):
    """Returns list of (p0, h1, h2, p3, end_smooth) cubic tuples covering sub."""
    (h1, h2), err, worst = fit_one(sub, t1, t2)
    if err <= FIT_ERR or depth >= 3 or worst < 4 or worst > len(sub) - 4:
        return [(sub[0], h1, h2, sub[-1])]
    mid_t = vnorm(vsub(sub[min(worst + 2, len(sub) - 1)], sub[max(worst - 2, 0)]))
    left = fit_span(sub[: worst + 1], t1, vmul(mid_t, -1.0), depth + 1)
    right = fit_span(sub[worst:], mid_t, t2, depth + 1)
    return left + right

# ---------- path rebuild ----------

def rebuild_path(path, metrics):
    raw = sample_path(path)
    if raw is None:
        return None, 0
    pts = resample(raw, path.closed)
    if len(pts) < 16:
        return None, 0
    sm = smooth_poly(pts, path.closed)
    keys = collect_keys(sm, path.closed)
    if len(keys) < 2:
        return None, 0
    n = len(sm)
    if path.closed:
        shift = keys[0].idx
        sm = sm[shift:] + sm[:shift]
        for k in keys:
            k.idx = (k.idx - shift) % n
        keys.sort(key=lambda k: k.idx)
    assign_geometry(keys, sm, path.closed, metrics)
    if len(keys) < 2:
        return None, 0

    spans = []
    pairs = list(zip(keys, keys[1:]))
    if path.closed:
        pairs.append((keys[-1], keys[0]))
    for a, b in pairs:
        if path.closed and b is keys[0]:
            sub = sm[a.idx:] + sm[: b.idx + 1]
        else:
            sub = sm[a.idx: b.idx + 1]
        if len(sub) < 2:
            continue
        sub = [a.pos] + sub[1:-1] + [b.pos]
        chord = vsub(b.pos, a.pos)
        dev = max((vlen(vsub(p, vadd(a.pos, vmul(vnorm(chord), vdot(vsub(p, a.pos), vnorm(chord)))))) for p in sub), default=0)
        is_line = vlen(chord) > 1e-6 and dev <= max(LINE_DEV, vlen(chord) * 0.025)
        spans.append([a, b, sub, is_line])

    # snap near-h/v straight spans exactly onto axis
    for a, b, sub, is_line in spans:
        if not is_line:
            continue
        d = vsub(b.pos, a.pos)
        ang = math.degrees(math.atan2(d[1], d[0])) % 180
        if min(ang, 180 - ang) <= LINE_ANGLE_TOL:
            y = (a.pos[1] + b.pos[1]) / 2.0
            snapped = [m for m in metrics if abs(y - m) <= METRIC_TOL]
            y = snapped[0] if snapped else y
            a.pos, b.pos = (a.pos[0], y), (b.pos[0], y)
        elif abs(ang - 90) <= LINE_ANGLE_TOL:
            x = (a.pos[0] + b.pos[0]) / 2.0
            a.pos, b.pos = (x, a.pos[1]), (x, b.pos[1])

    new = GSPath()
    new.closed = path.closed
    if not path.closed:
        start = GSNode(NSPoint(keys[0].pos[0], keys[0].pos[1]), LINE)
        new.nodes.append(start)
    for a, b, sub, is_line in spans:
        sub[0], sub[-1] = a.pos, b.pos
        if is_line:
            node = GSNode(NSPoint(b.pos[0], b.pos[1]), LINE)
            node.smooth = not b.corner
            new.nodes.append(node)
            continue
        t1 = a.tangent or vnorm(vsub(sub[min(3, len(sub) - 1)], sub[0]))
        t2 = vmul(b.tangent, -1.0) if b.tangent else vnorm(vsub(sub[max(len(sub) - 4, 0)], sub[-1]))
        for p0, h1, h2, p3 in fit_span(sub, t1, t2):
            new.nodes.append(GSNode(NSPoint(h1[0], h1[1]), OFFCURVE))
            new.nodes.append(GSNode(NSPoint(h2[0], h2[1]), OFFCURVE))
            end = GSNode(NSPoint(p3[0], p3[1]), CURVE)
            end.smooth = True
            new.nodes.append(end)
    # mark corner nodes non-smooth
    for node in new.nodes:
        if node.type != OFFCURVE:
            for k in keys:
                if k.corner and abs(node.position.x - k.pos[0]) < 1 and abs(node.position.y - k.pos[1]) < 1:
                    node.smooth = False
    return new, len(keys)

# ---------- post passes ----------

def drop_collinear(path):
    """Merge chains of straight segments that lie on one line."""
    changed = True
    while changed:
        changed = False
        nodes = list(path.nodes)
        count = len(nodes)
        for i, node in enumerate(nodes):
            if node.type != LINE:
                continue
            if not path.closed and i in (0, count - 1):
                continue
            prev = nodes[(i - 1) % count]
            nxt = nodes[(i + 1) % count]
            if prev.type == OFFCURVE or nxt.type != LINE:
                continue
            a, b, p = prev.position, nxt.position, node.position
            chord = vnorm((b.x - a.x, b.y - a.y))
            rel = (p.x - a.x, p.y - a.y)
            perp = vlen(vsub(rel, vmul(chord, vdot(rel, chord))))
            if perp <= LINE_DEV:
                path.nodes.remove(node)
                changed = True
                break


def orthogonalize_handles(path):
    nodes = list(path.nodes)
    count = len(nodes)
    for i, node in enumerate(nodes):
        if node.type == OFFCURVE:
            continue
        for j in ((i - 1) % count, (i + 1) % count):
            h = nodes[j]
            if h.type != OFFCURVE:
                continue
            v = (h.position.x - node.position.x, h.position.y - node.position.y)
            ang = math.degrees(math.atan2(v[1], v[0])) % 180
            if abs(ang - 90) <= LINE_ANGLE_TOL:
                h.position = NSPoint(node.position.x, h.position.y)
            elif min(ang, 180 - ang) <= LINE_ANGLE_TOL:
                h.position = NSPoint(h.position.x, node.position.y)

def equalize_tension(path):
    nodes = list(path.nodes)
    count = len(nodes)
    for i, node in enumerate(nodes):
        if node.type != CURVE:
            continue
        h2 = nodes[(i - 1) % count]
        h1 = nodes[(i - 2) % count]
        p0 = nodes[(i - 3) % count]
        if h1.type != OFFCURVE or h2.type != OFFCURVE or p0.type == OFFCURVE:
            continue
        t0 = (h1.position.x - p0.position.x, h1.position.y - p0.position.y)
        t3 = (h2.position.x - node.position.x, h2.position.y - node.position.y)
        if vlen(t0) < 0.01 or vlen(t3) < 0.01:
            continue
        cross = t0[0] * t3[1] - t0[1] * t3[0]
        if abs(cross) < 1e-6:
            continue
        d = (node.position.x - p0.position.x, node.position.y - p0.position.y)
        a = (d[0] * t3[1] - d[1] * t3[0]) / cross
        b = (d[0] * t0[1] - d[1] * t0[0]) / cross
        if a <= 0 or b <= 0:
            continue
        h1.position = NSPoint(p0.position.x + t0[0] * a * TENSION, p0.position.y + t0[1] * a * TENSION)
        h2.position = NSPoint(node.position.x + t3[0] * b * TENSION, node.position.y + t3[1] * b * TENSION)

# ---------- main ----------

font = Glyphs.font
font.disableUpdateInterface()
try:
    for layer in font.selectedLayers:
        glyph = layer.parent
        master = layer.master
        metrics = sorted({master.descender, 0.0, master.xHeight, master.capHeight, master.ascender})

        glyph.beginUndo()
        layer.setBackground_(layer)

        new_shapes = []
        rebuilt = 0
        for shape in layer.shapes:
            if isinstance(shape, GSPath):
                new_path, nkeys = rebuild_path(shape, metrics)
                if new_path is not None:
                    drop_collinear(new_path)
                    orthogonalize_handles(new_path)
                    equalize_tension(new_path)
                    for node in new_path.nodes:
                        node.position = NSPoint(round(node.position.x), round(node.position.y))
                    new_shapes.append(new_path)
                    rebuilt += 1
                    continue
            new_shapes.append(shape)
        layer.shapes = new_shapes
        try:
            layer.correctPathDirection()
        except Exception:
            pass

        glyph.endUndo()
        print("%s: rebuilt %d path(s) from corners+extremes (original in background)" % (glyph.name, rebuilt))
finally:
    font.enableUpdateInterface()
    Glyphs.redraw()
