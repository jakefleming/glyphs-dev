"""Independent re-implementation of Italify's curve correction (as decoded from its
debug log), to verify against its actual output on the VC Henrietta 'a'.

Rule (pre-distortion of the UPRIGHT outline, then plain shear about (0, xHeight/2)):
  * split each path into arc segments at axis extremes (nodes whose tangent is
    horizontal or vertical);
  * for each arc: C = intersection of the tangent lines at its ends ("corner");
    s = sign(dx*dy) with (dx,dy) = C - chord midpoint  (+1: corner in a "/"
    quadrant BL/TR,  -1: corner in a "\\" quadrant TL/BR);
    every control point on the legs (start, both handles, end) is scaled about C
    by  f = 1 + s * theta_rad * curveFactor;
  * a node shared by two arcs takes the SMALLER of the two displacements;
  * lines untouched (diagonal/stem corrections need tagged stems).
Chains (non-extreme intermediate nodes) use a different construction; those
nodes are flagged rather than reproduced here.
"""
import json, math

def unit(x, y):
    l = math.hypot(x, y)
    return (x / l, y / l) if l > 1e-9 else None

def is_axis(t, tol=0.02):
    return t is not None and (abs(t[0]) < tol or abs(t[1]) < tol)

def italify_curve_correction(paths, theta_deg, curve_factor=1.0):
    th = math.radians(theta_deg) * curve_factor
    out = []
    flags = []
    for nodes in paths:
        pts = [(x, y) for x, y, t in nodes]
        types = [t for x, y, t in nodes]
        cnt = len(nodes)
        new = list(pts)
        moved = [[] for _ in range(cnt)]  # candidate displacements per node
        flag = [""] * cnt
        # walk on-curve nodes; for each curve segment starting there
        for i in range(cnt):
            if types[i] == 'offcurve':
                continue
            j = (i + 1) % cnt
            if types[j] != 'offcurve':
                continue  # line
            h1, h2, e = j, (i + 2) % cnt, (i + 3) % cnt
            A, H1, H2, B = pts[i], pts[h1], pts[h2], pts[e]
            tA = unit(H1[0] - A[0], H1[1] - A[1]) or unit(B[0] - A[0], B[1] - A[1])
            tB = unit(B[0] - H2[0], B[1] - H2[1]) or unit(B[0] - A[0], B[1] - A[1])
            if not (is_axis(tA) and is_axis(tB)):
                flag[i] += "chain "
                flag[e] += "chain "
                continue
            # corner: intersection of tangent lines
            den = tA[0] * tB[1] - tA[1] * tB[0]
            if abs(den) < 1e-9:
                flag[i] += "parallel "
                flag[e] += "parallel "
                continue
            qx, qy = B[0] - A[0], B[1] - A[1]
            ta = (qx * tB[1] - qy * tB[0]) / den
            C = (A[0] + tA[0] * ta, A[1] + tA[1] * ta)
            M = ((A[0] + B[0]) / 2.0, (A[1] + B[1]) / 2.0)
            dx, dy = C[0] - M[0], C[1] - M[1]
            s = 1.0 if dx * dy > 0 else -1.0
            f = 1.0 + s * th
            for idx in (i, h1, h2, e):
                P = pts[idx]
                Pn = (C[0] + f * (P[0] - C[0]), C[1] + f * (P[1] - C[1]))
                moved[idx].append((Pn[0] - P[0], Pn[1] - P[1]))
        for idx in range(cnt):
            if moved[idx]:
                d = min(moved[idx], key=lambda v: math.hypot(*v))
                new[idx] = (pts[idx][0] + d[0], pts[idx][1] + d[1])
        out.append([(x, y, t) for (x, y), t in zip(new, types)])
        flags.append(flag)
    return out, flags

if __name__ == "__main__":
    up = json.load(open('/tmp/up_nodes.json')); it = json.load(open('/tmp/it_nodes.json'))
    theta = 12.0
    pre, flags = italify_curve_correction(up, theta)
    k = math.tan(math.radians(theta)); y0 = 263.5  # log: origin=(0, xHeight/2)
    mine = [[(x + (y - y0) * k, y, t) for x, y, t in p] for p in pre]
    tot = 0; n = 0; bad = []
    for pi, (pm, pit, fl) in enumerate(zip(mine, it, flags)):
        for i, (a, b) in enumerate(zip(pm, pit)):
            d = math.hypot(a[0] - b[0], a[1] - b[1])
            if not fl[i]:
                tot += d; n += 1
                if d > 1.5:
                    bad.append((pi, i, a[2], round(d, 1), fl[i]))
    print("regular-segment nodes: %d, mean |mine - Italify| = %.2f units" % (n, tot / max(n, 1)))
    print("nodes off by >1.5:", bad)
    chain_nodes = [(pi, i) for pi, fl in enumerate(flags) for i, f in enumerate(fl) if f]
    print("chain/parallel-flagged nodes (not modelled):", len(chain_nodes), chain_nodes)
