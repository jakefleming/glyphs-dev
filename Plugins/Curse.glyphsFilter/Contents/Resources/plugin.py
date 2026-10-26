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
from AppKit import NSView, NSSlider, NSTextField, NSButton, NSMakeRect, NSFont, NSPopover, NSViewController
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
		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 178))

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
			parent.addSubview_(f)
			return f

		self._mainView = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 178))
		view.addSubview_(self._mainView)
		label("Angle", 16, 139, 160, self._mainView)
		self.angleField = field("12°", 262, 138, self._mainView)
		self.angleField.setToolTip_("Degrees to add. Negative values lean left.")
		label("Balance", 16, 107, 160, self._mainView)
		self.balanceField = field("100%", 262, 82, self._mainView)
		self.balanceSlider = NSSlider.alloc().initWithFrame_(NSMakeRect(16, 82, 232, 22))
		self.balanceSlider.setMinValue_(0)
		self.balanceSlider.setMaxValue_(100)
		self.balanceSlider.setDoubleValue_(100)
		self.balanceSlider.setContinuous_(False)
		self.balanceSlider.setTarget_(self)
		self.balanceSlider.setAction_("balanceChanged:")
		self.balanceSlider.setToolTip_("Blend from a plain slant to the corrected outline.")
		self._mainView.addSubview_(self.balanceSlider)
		self.detailButton = NSButton.alloc().initWithFrame_(NSMakeRect(12, 45, 160, 24))
		self.detailButton.setButtonType_(0)
		self.detailButton.setBezelStyle_(0)
		self.detailButton.setTitle_("Fine tune…")
		self.detailButton.setTarget_(self)
		self.detailButton.setAction_("toggleDetails:")
		self._mainView.addSubview_(self.detailButton)
		self.status = label("Preview the selected outlines, then Apply.", 16, 10, 310, self._mainView, 11)

		self._detailView = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 142))
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
		self._detailController = NSViewController.alloc().init()
		self._detailController.setView_(self._detailView)
		self._popover = NSPopover.alloc().init()
		self._popover.setContentViewController_(self._detailController)
		self._popover.setBehavior_(1)
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

	def toggleDetails_(self, sender):
		if self._popover.isShown():
			self._popover.close()
		else:
			self._popover.showRelativeToRect_ofView_preferredEdge_(sender.bounds(), sender, 1)

	def balanceChanged_(self, sender):
		self.balanceField.setStringValue_("%g%%" % round(self.balanceSlider.doubleValue()))
		self.update()

	def fieldChanged_(self, sender):
		try:
			v = float(sender.stringValue().replace("°", "").replace("%", "").strip())
			if not math.isfinite(v):
				raise ValueError("Enter a finite number")
			if sender is self.angleField:
				self._angle = max(-35., min(35., v))
			elif sender is self.balanceField:
				self.balanceSlider.setDoubleValue_(max(0., min(100., v)))
			else:
				for key, f in self._fields.items():
					if sender is f:
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
	def italicize(self, layer, angleDeg, curve, keepTerm, diag, stem, restoreVerticals):
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
		if curve > 0:
			for path, segs in zip(closed, pathSegs):
				if segs is None:
					continue
				nodes = list(path.nodes)
				nseg = len(segs)
				proposals = {}   # node index -> list of (dx, dy)
				handleMove = {}  # offcurve index -> (dx, dy, nodeIndex, nodeOwnProposal)

				# pre-compute each curve segment's extended arc, so neighbours can
				# refer to the tangent at its implicit extreme (its corner leg)
				extCache = {}
				for si, seg in enumerate(segs):
					if seg['c1'] is None:
						continue
					C = (seg['A'], seg['c1'], seg['c2'], seg['B'])
					t0, t1 = _extend(C, extBounds)
					E = _sub(C, t0, t1)
					extCache[si] = (E, _unit(*_bezD(E, 0.0)), _unit(*_bezD(E, 1.0)))

				def farTangentLine(other, atStart):
					"""Tangent line (point, dir) at the far end of a neighbouring
					segment -- for curves, at the far end of its EXTENDED arc, so
					the cap lands on that arc's corner leg (its limiting tangent)."""
					if other['c1'] is None:
						d = _unit(other['B'][0] - other['A'][0], other['B'][1] - other['A'][1])
						return (other['A'] if atStart else other['B']), d
					oi = segs.index(other)
					if oi in extCache:
						E_o, d0, d3 = extCache[oi]
						return (E_o[0], d0) if atStart else (E_o[3], d3)
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

					t0, t1 = _extend(C, extBounds)
					E = _sub(C, t0, t1)
					dE0 = _unit(*_bezD(E, 0.0))
					dE3 = _unit(*_bezD(E, 1.0))
					if dE0 is None or dE3 is None:
						noCorner()
						continue
					# A segment is treated as round only if at least one end
					# sits on an axis extreme (real or reached by extension); a
					# shallow curve with neither is left alone (v/w/x sides, terminals)
					if _axisKind(dE0) is None and _axisKind(dE3) is None:
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
					# nearly-parallel end tangents: the corner runs off to infinity
					# and is useless as a pivot (a b's long stem-curve, a straight
					# side drawn as one shallow arc). Treat it as straight.
					chordE = math.hypot(E[3][0] - E[0][0], E[3][1] - E[0][1])
					if math.hypot(corner[0] - mid[0], corner[1] - mid[1]) > CORNER_FAR * chordE:
						noCorner()
						continue
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
						capped = False
						if fd is not None:
							far = _rayInt(N, tN, fp, fd)
							if far is not None:
								F = far[0]
								dF = abs((F[0] - N[0]) * tN[0] + (F[1] - N[1]) * tN[1])
								dN = min(dN, dF)
								dH = min(dH, abs((F[0] - H[0]) * tN[0] + (F[1] - H[1]) * tN[1]))
								capped = True
						if not capped and otherSeg['c1'] is not None:
							# The neighbouring ARC runs parallel to this tangent (a
							# u's straight left side) so it yields no cap and the
							# node would slide to a far-away corner. Bound it by
							# that arc's own half extent. Line neighbours are left
							# to the clip step, which re-intersects with the stem.
							oA, oB = otherSeg['A'], otherSeg['B']
							chordOther = math.hypot(oB[0] - oA[0], oB[1] - oA[1])
							if chordOther > 1e-6:
								dN = min(dN, 0.5 * chordOther)
								dH = min(dH, 0.5 * chordOther)
						sign = -s * toward   # shrink (s=-1) -> toward the corner
						chordAB = math.hypot(B[0] - A[0], B[1] - A[1])
						dN = min(dN, 2.0 * chordAB)
						dH = min(dH, 2.0 * chordAB)
						return ((sign * strength * dN * tN[0], sign * strength * dN * tN[1]),
							(sign * strength * dH * tN[0], sign * strength * dH * tN[1]))

					mvA, mv1 = endMove(A, tA, c1, prev, True)
					mvB, mv2 = endMove(B, tB, c2, nxt, False)

					# corrected extended arc, for clipping against adjoining lines
					f = 1.0 + s * strength
					E2 = tuple((corner[0] + f * (P[0] - corner[0]), corner[1] + f * (P[1] - corner[1])) for P in E)
					span = (t1 - t0) if abs(t1 - t0) > 1e-9 else 1.0
					u0 = (0.0 - t0) / span
					u1 = (1.0 - t0) / span

					def clipEnd(lineSeg, atStart):
						"""Place the node at the intersection of the corrected
						extended arc with the neighbouring straight line; the
						handles come from re-splitting the arc there."""
						u = self._clipToLine(E2, u0 if atStart else u1, lineSeg['A'], lineSeg['B'])
						if u is None:
							return None
						S = _sub(E2, u, u1) if atStart else _sub(E2, u0, u)
						return S

					chordAB = math.hypot(B[0] - A[0], B[1] - A[1])
					clipLimit = abs(strength) * 2.0 * chordAB + 2.0   # seg-clip-limit
					if prev['c1'] is None:
						S = clipEnd(prev, True)
						if S is not None and math.hypot(S[0][0] - A[0], S[0][1] - A[1]) <= clipLimit:
							mvA = (S[0][0] - A[0], S[0][1] - A[1])
							mv1 = (S[1][0] - c1[0], S[1][1] - c1[1])
					if nxt['c1'] is None:
						S = clipEnd(nxt, False)
						if S is not None and math.hypot(S[3][0] - B[0], S[3][1] - B[1]) <= clipLimit:
							mvB = (S[3][0] - B[0], S[3][1] - B[1])
							mv2 = (S[2][0] - c2[0], S[2][1] - c2[1])

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
		# Slide each formerly-vertical-extreme node along the
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
			self.italicize(layer, angle, amount('curve'), amount('terminals'), amount('diagonal'), amount('stem'), verts)
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
		return "%s; angle:%g; curve:%g; terminals:%g; diagonal:%g; stem:%g; extremes:%d" % (
			self.__class__.__name__, self._angle, self.val('curve'), self.val('terminals'),
			self.val('diagonal'), self.val('stem'),
			1 if self.vertCheck.state() and self.balanceSlider.doubleValue() > 0 else 0)

	@objc.python_method
	def __file__(self):
		return __file__
