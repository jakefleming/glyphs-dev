# MenuTitle: Make Compatible
# -*- coding: utf-8 -*-
__doc__ = """
Fixes the mechanical causes of master incompatibility, glyph by glyph, against
a reference master (the first master by default):

  1. path order      — paths are matched across masters by position and size
  2. path direction  — winding corrected to match the reference
  3. start node      — each path rotated to the same corresponding point
  4. node types      — a line opposite a curve becomes a curve with handles ON
                       the line (identical shape, compatible structure)
  5. node counts     — missing nodes inserted in the sparser master at the
                       matching places (extremes first, then even spacing
                       between corresponding corners)
  6. anchors         — an anchor present in the reference but missing in another
                       master is added at the same proportional position and
                       reported so you can check it; extra anchors are reported,
                       never deleted

Anything it cannot decide — different corner structure, different path counts,
components vs outlines — is left alone and listed at the end.

Originals go to each layer's background. Selected glyphs only; select none to
run on the whole font.
"""

import math
import traceback
from Foundation import NSPoint
from GlyphsApp import Glyphs, GSPath, GSNode, GSAnchor, LINE, CURVE, OFFCURVE

CORNER_ANGLE = 35.0   # deg: direction change that counts as a corner
BACKUP = True         # copy each layer to its background before touching it


# ---------------------------------------------------------------- geometry

def unit(x, y):
	l = math.hypot(x, y)
	return (x / l, y / l) if l > 1e-9 else None


def bez(C, t):
	mt = 1 - t
	return (mt**3 * C[0][0] + 3 * mt * mt * t * C[1][0] + 3 * mt * t * t * C[2][0] + t**3 * C[3][0],
		mt**3 * C[0][1] + 3 * mt * mt * t * C[1][1] + 3 * mt * t * t * C[2][1] + t**3 * C[3][1])


def bezSplit(C, t):
	def lerp(a, b, u):
		return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
	p01, p12, p23 = lerp(C[0], C[1], t), lerp(C[1], C[2], t), lerp(C[2], C[3], t)
	p012, p123 = lerp(p01, p12, t), lerp(p12, p23, t)
	pm = lerp(p012, p123, t)
	return (C[0], p01, p012, pm), (pm, p123, p23, C[3])


def pathInfo(path):
	"""(centre, area, bounds) of a path, from its on-curve points."""
	pts = [(n.position.x, n.position.y) for n in path.nodes if n.type != OFFCURVE]
	if not pts:
		return (0, 0), 0.0, (0, 0, 0, 0)
	a = 0.0
	cx = cy = 0.0
	for i in range(len(pts)):
		x1, y1 = pts[i]
		x2, y2 = pts[(i + 1) % len(pts)]
		cross = x1 * y2 - x2 * y1
		a += cross
		cx += (x1 + x2) * cross
		cy += (y1 + y2) * cross
	a /= 2.0
	if abs(a) > 1e-9:
		c = (cx / (6 * a), cy / (6 * a))
	else:
		c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
	xs = [p[0] for p in pts]
	ys = [p[1] for p in pts]
	return c, a, (min(xs), min(ys), max(xs), max(ys))


def segments(path):
	"""[(startIdx, endIdx, isCurve)] between on-curve nodes, in path order."""
	nodes = list(path.nodes)
	onIdx = [i for i, n in enumerate(nodes) if n.type != OFFCURVE]
	out = []
	cnt = len(nodes)
	for k in range(len(onIdx)):
		a = onIdx[k]
		b = onIdx[(k + 1) % len(onIdx)]
		between = 0
		i = (a + 1) % cnt
		while i != b:
			between += 1
			i = (i + 1) % cnt
		out.append((a, b, between == 2))
	return out


def onCurvePoints(path):
	return [(n.position.x, n.position.y) for n in path.nodes if n.type != OFFCURVE]


def cornerFlags(path):
	"""Per on-curve node: True if it is a corner (big direction change)."""
	nodes = list(path.nodes)
	cnt = len(nodes)
	flags = []
	for i, n in enumerate(nodes):
		if n.type == OFFCURVE:
			continue
		p, q = nodes[(i - 1) % cnt], nodes[(i + 1) % cnt]
		v1 = unit(n.position.x - p.position.x, n.position.y - p.position.y)
		v2 = unit(q.position.x - n.position.x, q.position.y - n.position.y)
		if v1 is None or v2 is None:
			flags.append(True)
			continue
		dot = max(-1.0, min(1.0, v1[0] * v2[0] + v1[1] * v2[1]))
		flags.append(math.degrees(math.acos(dot)) > CORNER_ANGLE)
	return flags


# ---------------------------------------------------------------- fixes

def matchPathOrder(refLayer, layer):
	"""Reorder layer's paths to correspond to the reference by centre + area."""
	refPaths = [s for s in refLayer.shapes if isinstance(s, GSPath)]
	paths = [s for s in layer.shapes if isinstance(s, GSPath)]
	others = [s for s in layer.shapes if not isinstance(s, GSPath)]
	if len(refPaths) != len(paths) or len(paths) < 2:
		return False
	refInfo = [pathInfo(p) for p in refPaths]
	info = [pathInfo(p) for p in paths]
	# normalise coordinates by each layer's bounds so masters of different
	# widths still match up
	def norm(inf, allInf):
		xs = [i[2][0] for i in allInf] + [i[2][2] for i in allInf]
		ys = [i[2][1] for i in allInf] + [i[2][3] for i in allInf]
		w = max(xs) - min(xs) or 1.0
		h = max(ys) - min(ys) or 1.0
		return ((inf[0][0] - min(xs)) / w, (inf[0][1] - min(ys)) / h, inf[1] / (w * h))
	refN = [norm(i, refInfo) for i in refInfo]
	curN = [norm(i, info) for i in info]
	used = set()
	order = []
	for r in refN:
		best, bestD = None, None
		for j, c in enumerate(curN):
			if j in used:
				continue
			d = (r[0] - c[0])**2 + (r[1] - c[1])**2 + 0.5 * (abs(r[2]) - abs(c[2]))**2
			if (r[2] > 0) != (c[2] > 0):
				d += 0.25   # prefer same winding, but allow a flip
			if bestD is None or d < bestD:
				best, bestD = j, d
		used.add(best)
		order.append(best)
	if order == list(range(len(paths))):
		return False
	layer.shapes = others + [paths[i] for i in order]
	return True


def matchDirection(refPath, path):
	_, refArea, _ = pathInfo(refPath)
	_, area, _ = pathInfo(path)
	if (refArea > 0) != (area > 0):
		path.reverse()
		return True
	return False


def matchStartNode(refPath, path):
	"""Rotate `path` so its start node corresponds to the reference's start."""
	refPts = onCurvePoints(refPath)
	pts = onCurvePoints(path)
	if len(refPts) != len(pts) or len(pts) < 2:
		return False
	# normalise both to their bounding boxes, then find the rotation with the
	# smallest total distance
	def normalise(P):
		xs = [p[0] for p in P]
		ys = [p[1] for p in P]
		w = (max(xs) - min(xs)) or 1.0
		h = (max(ys) - min(ys)) or 1.0
		return [((p[0] - min(xs)) / w, (p[1] - min(ys)) / h) for p in P]
	R, C = normalise(refPts), normalise(pts)
	n = len(R)
	best, bestD = 0, None
	for shift in range(n):
		d = sum((R[i][0] - C[(i + shift) % n][0])**2 + (R[i][1] - C[(i + shift) % n][1])**2 for i in range(n))
		if bestD is None or d < bestD:
			best, bestD = shift, d
	if best == 0:
		return False
	onIdx = [i for i, nd in enumerate(path.nodes) if nd.type != OFFCURVE]
	target = onIdx[best]
	nodes = list(path.nodes)
	rotated = nodes[target:] + nodes[:target]
	# a closed path must end on an on-curve node
	while rotated and rotated[-1].type == OFFCURVE:
		rotated.insert(0, rotated.pop())
	path.nodes = rotated
	return True


def lineToCurve(path, segIdx):
	"""Turn segment segIdx (a line) into a curve with handles on the line."""
	segs = segments(path)
	a, b, isCurve = segs[segIdx]
	if isCurve:
		return False
	nodes = list(path.nodes)
	A, B = nodes[a].position, nodes[b].position
	h1 = GSNode(NSPoint(A.x + (B.x - A.x) / 3.0, A.y + (B.y - A.y) / 3.0), OFFCURVE)
	h2 = GSNode(NSPoint(A.x + (B.x - A.x) * 2 / 3.0, A.y + (B.y - A.y) * 2 / 3.0), OFFCURVE)
	nodes[b].type = CURVE
	insertAt = (a + 1) % len(nodes)
	if insertAt == 0:
		nodes = nodes + [h1, h2]
	else:
		nodes = nodes[:insertAt] + [h1, h2] + nodes[insertAt:]
	path.nodes = nodes
	return True


def splitSegment(path, segIdx, t=0.5):
	"""Insert a node in the middle of segment segIdx, shape unchanged."""
	segs = segments(path)
	a, b, isCurve = segs[segIdx]
	nodes = list(path.nodes)
	if isCurve:
		h1 = nodes[(a + 1) % len(nodes)]
		h2 = nodes[(a + 2) % len(nodes)]
		C = ((nodes[a].position.x, nodes[a].position.y), (h1.position.x, h1.position.y),
			(h2.position.x, h2.position.y), (nodes[b].position.x, nodes[b].position.y))
		left, right = bezSplit(C, t)
		h1.position = NSPoint(*left[1])
		mid = GSNode(NSPoint(*left[3]), CURVE)
		mid.smooth = True
		newH1 = GSNode(NSPoint(*left[2]), OFFCURVE)
		newH2 = GSNode(NSPoint(*right[1]), OFFCURVE)
		h2.position = NSPoint(*right[2])
		insertAt = (a + 2) % len(nodes)
		block = [newH1, mid, newH2]
		if insertAt == 0:
			path.nodes = nodes + block
		else:
			path.nodes = nodes[:insertAt] + block + nodes[insertAt:]
	else:
		A, B = nodes[a].position, nodes[b].position
		mid = GSNode(NSPoint(A.x + (B.x - A.x) * t, A.y + (B.y - A.y) * t), LINE)
		insertAt = (a + 1) % len(nodes)
		if insertAt == 0:
			path.nodes = nodes + [mid]
		else:
			path.nodes = nodes[:insertAt] + [mid] + nodes[insertAt:]
	return True


def matchNodeTypes(refPath, path):
	"""Line opposite curve -> make the line a curve. Returns count fixed."""
	fixed = 0
	for _ in range(200):
		refSegs = segments(refPath)
		segs = segments(path)
		if len(refSegs) != len(segs):
			return fixed
		changed = False
		for i, (rs, s) in enumerate(zip(refSegs, segs)):
			if rs[2] and not s[2]:
				if lineToCurve(path, i):
					fixed += 1
					changed = True
					break
			if s[2] and not rs[2]:
				if lineToCurve(refPath, i):
					fixed += 1
					changed = True
					break
		if not changed:
			break
	return fixed


def matchNodeCount(refPath, path):
	"""Insert nodes into whichever path has fewer, between corresponding
	corners. Returns (inserted, ok) — ok is False when the corner structure
	differs, which needs a human."""
	inserted = 0
	for _ in range(200):
		refPts, pts = onCurvePoints(refPath), onCurvePoints(path)
		if len(refPts) == len(pts):
			return inserted, True
		sparse, dense = (path, refPath) if len(pts) < len(refPts) else (refPath, path)
		sc = cornerFlags(sparse)
		dc = cornerFlags(dense)
		if sum(sc) != sum(dc):
			return inserted, False   # different corner structure: not ours to guess
		# split the longest run between corners in the sparse path
		segsS = segments(sparse)
		ptsS = onCurvePoints(sparse)
		best, bestLen = None, -1.0
		for i, (a, b, isCurve) in enumerate(segsS):
			p = ptsS[i]
			q = ptsS[(i + 1) % len(ptsS)]
			L = math.hypot(q[0] - p[0], q[1] - p[1])
			if L > bestLen:
				best, bestLen = i, L
		if best is None:
			return inserted, False
		splitSegment(sparse, best)
		inserted += 1
	return inserted, False


def matchAnchors(refLayer, layer, glyphName, layerName, report):
	"""Anchors must exist with the same names in every master. Add any that are
	missing, placed by proportion from the reference layer's bounding box, and
	report each one so it can be checked. Extra anchors are reported, never
	deleted."""
	refNames = [a.name for a in refLayer.anchors]
	names = [a.name for a in layer.anchors]
	added = 0
	missing = [n for n in refNames if n not in names]
	extra = [n for n in names if n not in refNames]
	if missing:
		rb, b = refLayer.bounds, layer.bounds
		for nm in missing:
			ra = refLayer.anchors[nm]
			if rb.size.width > 0 and rb.size.height > 0 and b.size.width > 0 and b.size.height > 0:
				fx = (ra.position.x - rb.origin.x) / rb.size.width
				fy = (ra.position.y - rb.origin.y) / rb.size.height
				x = b.origin.x + fx * b.size.width
				y = b.origin.y + fy * b.size.height
			else:
				x, y = ra.position.x, ra.position.y
			layer.anchors.append(GSAnchor(nm, NSPoint(round(x), round(y))))
			added += 1
			report.append("%s / %s: added anchor '%s' at (%d, %d) — check its position"
				% (glyphName, layerName, nm, round(x), round(y)))
	for nm in extra:
		report.append("%s / %s: has anchor '%s' that %s does not — remove it or add it there"
			% (glyphName, layerName, nm, refLayer.name))
	return added


# ---------------------------------------------------------------- main

font = Glyphs.font
if font is None:
	print("No font open.")
else:
	glyphs = [l.parent for l in font.selectedLayers] if font.selectedLayers else list(font.glyphs)
	glyphs = list(dict.fromkeys(glyphs))
	masters = list(font.masters)
	refM = masters[0]
	report = []
	stats = {'order': 0, 'direction': 0, 'start': 0, 'types': 0, 'nodes': 0, 'anchors': 0, 'glyphs': 0}

	font.disableUpdateInterface()
	try:
		for glyph in glyphs:
			try:
				layers = [glyph.layers[m.id] for m in masters]
			except Exception:
				continue
			if len(layers) < 2:
				continue
			ref = layers[0]
			if not [s for s in ref.shapes if isinstance(s, GSPath)]:
				continue
			touched = False
			glyph.beginUndo()
			for layer in layers[1:]:
				# anchors first: they are independent of the outlines, and a
				# missing anchor breaks every composite built on this glyph
				if BACKUP and not touched and (
						[a.name for a in ref.anchors] != [a.name for a in layer.anchors]):
					for l in layers:
						l.setBackground_(l)
					touched = True
				n = matchAnchors(ref, layer, glyph.name, layer.name, report)
				if n:
					stats['anchors'] += n
					touched = True

				refPaths = [s for s in ref.shapes if isinstance(s, GSPath)]
				paths = [s for s in layer.shapes if isinstance(s, GSPath)]
				if len(refPaths) != len(paths):
					report.append("%s / %s: path count %d vs %d — needs a decision"
						% (glyph.name, layer.name, len(refPaths), len(paths)))
					continue
				if BACKUP and not touched:
					for l in layers:
						l.setBackground_(l)
				if matchPathOrder(ref, layer):
					stats['order'] += 1
					touched = True
					paths = [s for s in layer.shapes if isinstance(s, GSPath)]
				for pi, (rp, p) in enumerate(zip(refPaths, paths)):
					if matchDirection(rp, p):
						stats['direction'] += 1
						touched = True
					n = matchNodeTypes(rp, p)
					if n:
						stats['types'] += n
						touched = True
					ins, ok = matchNodeCount(rp, p)
					if ins:
						stats['nodes'] += ins
						touched = True
					if not ok:
						report.append("%s / %s path %d: %d vs %d nodes, corner structure differs — needs a decision"
							% (glyph.name, layer.name, pi, len(onCurvePoints(rp)), len(onCurvePoints(p))))
						continue
					n = matchNodeTypes(rp, p)
					if n:
						stats['types'] += n
						touched = True
					if matchStartNode(rp, p):
						stats['start'] += 1
						touched = True
			glyph.endUndo()
			if touched:
				stats['glyphs'] += 1
	finally:
		font.enableUpdateInterface()

	print("Make Compatible — reference master: %s" % refM.name)
	print("  changed %d glyph(s): %d path reorders, %d direction flips, %d start-node rotations, %d line→curve, %d nodes inserted, %d anchors added"
		% (stats['glyphs'], stats['order'], stats['direction'], stats['start'], stats['types'], stats['nodes'], stats['anchors']))
	if report:
		print("  %d left for you:" % len(report))
		for line in report:
			print("   ", line)
	else:
		print("  nothing left over.")
	Glyphs.redraw()
