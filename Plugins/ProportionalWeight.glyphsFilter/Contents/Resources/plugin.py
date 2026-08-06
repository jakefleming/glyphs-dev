# encoding: utf-8
from __future__ import division, print_function, unicode_literals

import objc
import math
import traceback
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, CURVE, OFFCURVE
from GlyphsApp.plugins import FilterWithDialog
from AppKit import (NSView, NSSlider, NSTextField, NSMakeRect, NSFont, NSButton,
	NSColor, NSBezierPath)
from Foundation import NSMakePoint

MITER_LIMIT = 10  # max corner extension, in multiples of the offset amount
WELD_EPS = 0.25  # endpoints closer than this are welded, not joined
PAD_RANGE = 60  # units of counter shift at full pad deflection


class ProportionalWeightPad(NSView):
	"""2D XY pad: drag the dot to shift counters. Center = no shift."""

	def acceptsFirstMouse_(self, event):
		return True

	def mouseDownCanMoveWindow(self):
		return False

	def drawRect_(self, rect):
		b = self.bounds()
		inset = 10
		NSColor.controlBackgroundColor().set()
		NSBezierPath.fillRect_(b)
		NSColor.tertiaryLabelColor().set()
		box = NSBezierPath.bezierPathWithRect_(NSMakeRect(1, 1, b.size.width - 2, b.size.height - 2))
		box.setLineWidth_(1)
		box.stroke()
		# center tick marks
		cxm, cym = b.size.width / 2.0, b.size.height / 2.0
		for (x1, y1, x2, y2) in ((cxm, 3, cxm, 9), (cxm, b.size.height - 9, cxm, b.size.height - 3),
				(3, cym, 9, cym), (b.size.width - 9, cym, b.size.width - 3, cym)):
			p = NSBezierPath.bezierPath()
			p.moveToPoint_((x1, y1))
			p.lineToPoint_((x2, y2))
			p.setLineWidth_(1.5)
			p.stroke()
		val = getattr(self, 'val', (0.0, 0.0))
		dx = cxm + val[0] * (cxm - inset)
		dy = cym + val[1] * (cym - inset)
		NSColor.systemBlueColor().set()
		NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(dx - 7, dy - 7, 14, 14)).fill()

	def handleEvent_(self, event):
		p = self.convertPoint_fromView_(event.locationInWindow(), None)
		b = self.bounds()
		inset = 10
		nx = (p.x - b.size.width / 2.0) / (b.size.width / 2.0 - inset)
		ny = (p.y - b.size.height / 2.0) / (b.size.height / 2.0 - inset)
		self.val = (max(-1.0, min(1.0, nx)), max(-1.0, min(1.0, ny)))
		self.setNeedsDisplay_(True)
		owner = getattr(self, 'owner', None)
		if owner is not None:
			owner.padChanged()

	def mouseDown_(self, event):
		self.handleEvent_(event)

	def mouseDragged_(self, event):
		self.handleEvent_(event)


def _unit(dx, dy):
	l = math.hypot(dx, dy)
	if l < 1e-9:
		return None
	return (dx / l, dy / l)


def _rayIntersect(P, d1, Q, d2):
	"""Intersection of P+t*d1 and Q+s*d2. Returns (point, t, s) or None."""
	denom = d1[0] * d2[1] - d1[1] * d2[0]
	if abs(denom) < 1e-9:
		return None
	qx, qy = Q[0] - P[0], Q[1] - P[1]
	t = (qx * d2[1] - qy * d2[0]) / denom
	s = (qx * d1[1] - qy * d1[0]) / denom
	return ((P[0] + t * d1[0], P[1] + t * d1[1]), t, s)


def _lerpPt(a, b, t):
	return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _bezPt(C, t):
	mt = 1 - t
	return (mt**3 * C[0][0] + 3 * mt**2 * t * C[1][0] + 3 * mt * t**2 * C[2][0] + t**3 * C[3][0],
		mt**3 * C[0][1] + 3 * mt**2 * t * C[1][1] + 3 * mt * t**2 * C[2][1] + t**3 * C[3][1])


def _bezSplit(C, t):
	"""de Casteljau split: returns (left4, right4)."""
	p01 = _lerpPt(C[0], C[1], t)
	p12 = _lerpPt(C[1], C[2], t)
	p23 = _lerpPt(C[2], C[3], t)
	p012 = _lerpPt(p01, p12, t)
	p123 = _lerpPt(p12, p23, t)
	p = _lerpPt(p012, p123, t)
	return (C[0], p01, p012, p), (p, p123, p23, C[3])


def _segSegX(a, b, c, d):
	r = (b[0] - a[0], b[1] - a[1])
	s = (d[0] - c[0], d[1] - c[1])
	den = r[0] * s[1] - r[1] * s[0]
	if abs(den) < 1e-12:
		return None
	q = (c[0] - a[0], c[1] - a[1])
	u = (q[0] * s[1] - q[1] * s[0]) / den
	v = (q[0] * r[1] - q[1] * r[0]) / den
	if -0.001 <= u <= 1.001 and -0.001 <= v <= 1.001:
		return u, v, (a[0] + u * r[0], a[1] + u * r[1])
	return None


def _crossElems(Apts, Bpts):
	"""First crossing between two polylines, preferring near A's end and
	B's start. Skips the shared corner point itself. Returns (tA, tB, X)."""
	best = None
	na, nb = len(Apts) - 1, len(Bpts) - 1
	for i in range(na):
		for j in range(nb):
			r = _segSegX(Apts[i], Apts[i + 1], Bpts[j], Bpts[j + 1])
			if r is None:
				continue
			u, v, X = r
			tA = (i + u) / na
			tB = (j + v) / nb
			if tA > 0.999 and tB < 0.001:
				continue
			score = (1 - tA) + tB
			if best is None or score < best[0]:
				best = (score, tA, tB, X)
	if best is None:
		return None
	return best[1], best[2], best[3]


class ProportionalWeight(FilterWithDialog):

	@objc.python_method
	def settings(self):
		self.menuName = "Proportional Weight"
		self.actionButtonLabel = "Apply"

		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 518))

		def label(text, y):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(12, y, 200, 17))
			f.setStringValue_(text)
			f.setBezeled_(False)
			f.setDrawsBackground_(False)
			f.setEditable_(False)
			f.setSelectable_(False)
			f.setFont_(NSFont.systemFontOfSize_(11))
			view.addSubview_(f)
			return f

		def valueField(y, initial):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(216, y - 2, 52, 20))
			f.setStringValue_(initial)
			f.setBezeled_(True)
			f.setDrawsBackground_(True)
			f.setEditable_(True)
			f.setSelectable_(True)
			f.setAlignment_(1)  # right-aligned on macOS
			f.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0))
			f.setTarget_(self)
			f.setAction_("fieldChanged:")
			view.addSubview_(f)
			return f

		def rowReset(y, tag):
			b = NSButton.alloc().initWithFrame_(NSMakeRect(192, y - 2, 20, 20))
			b.setTitle_("↺")
			b.setBordered_(False)
			b.setTarget_(self)
			b.setAction_("resetRow:")
			b.setTag_(tag)
			view.addSubview_(b)
			return b

		def slider(y, minV, maxV, initial):
			s = NSSlider.alloc().initWithFrame_(NSMakeRect(10, y, 258, 24))
			s.setMinValue_(minV)
			s.setMaxValue_(maxV)
			s.setDoubleValue_(initial)
			s.setContinuous_(True)
			s.setTarget_(self)
			s.setAction_("sliderCallback:")
			view.addSubview_(s)
			return s

		# convention: "no change" sits at the center of every slider.
		# Weight is units either side of 0; the % sliders run 0-200 with
		# neutral 100 centered. Harmony/Balance are effect strengths, so
		# their neutral (0 = off) is the left edge.
		resetBtn = NSButton.alloc().initWithFrame_(NSMakeRect(190, 486, 80, 26))
		resetBtn.setTitle_("Reset")
		resetBtn.setBezelStyle_(1)  # rounded
		resetBtn.setTarget_(self)
		resetBtn.setAction_("resetCallback:")
		view.addSubview_(resetBtn)

		label("Weight", 460)
		self.valueField = valueField(460, "+0")
		self.slider = slider(430, -200, 200, 0)
		rowReset(460, 0)

		label("Vertical", 406)
		self.vpctField = valueField(406, "100%")
		self.vpctSlider = slider(376, 0, 200, 100)
		rowReset(406, 1)

		label("Counters", 352)
		self.cpctField = valueField(352, "100%")
		self.cpctSlider = slider(322, 0, 200, 100)
		rowReset(352, 2)

		label("Width", 298)
		self.widthField = valueField(298, "100%")
		self.widthSlider = slider(268, 0, 200, 100)
		rowReset(298, 3)

		label("Harmony", 244)
		self.harmonyField = valueField(244, "0%")
		self.harmonySlider = slider(214, 0, 100, 0)
		rowReset(244, 4)

		label("Balance", 190)
		self.balanceField = valueField(190, "0%")
		self.balanceSlider = slider(160, 0, 100, 0)
		rowReset(190, 5)

		label("Counter Position", 130)
		self.padField = valueField(130, "0, 0")
		self.pad = ProportionalWeightPad.alloc().initWithFrame_(NSMakeRect(10, 10, 116, 116))
		self.pad.val = (0.0, 0.0)
		self.pad.owner = self
		view.addSubview_(self.pad)
		rowReset(130, 6)

		# row metadata for typed input and per-row reset:
		# field -> (slider, default) ; pad handled separately via tag 6
		self._rowBySlider = [
			(self.slider, self.valueField, 0),
			(self.vpctSlider, self.vpctField, 100),
			(self.cpctSlider, self.cpctField, 100),
			(self.widthSlider, self.widthField, 100),
			(self.harmonySlider, self.harmonyField, 0),
			(self.balanceSlider, self.balanceField, 0),
		]

		self.dialog = view
		self._origWidths = {}

	@objc.python_method
	def start(self):
		# new dialog session: current layer widths are the new baseline
		self._origWidths = {}

	def resetCallback_(self, sender):
		self.slider.setDoubleValue_(0)
		self.vpctSlider.setDoubleValue_(100)
		self.cpctSlider.setDoubleValue_(100)
		self.widthSlider.setDoubleValue_(100)
		self.harmonySlider.setDoubleValue_(0)
		self.balanceSlider.setDoubleValue_(0)
		self.pad.val = (0.0, 0.0)
		self.pad.setNeedsDisplay_(True)
		self.padField.setStringValue_("0, 0")
		self.sliderCallback_(sender)

	@objc.python_method
	def padChanged(self):
		self.padField.setStringValue_("%+d, %+d" % (
			round(self.pad.val[0] * PAD_RANGE), round(self.pad.val[1] * PAD_RANGE)))
		self.update()

	def resetRow_(self, sender):
		tag = sender.tag()
		if tag == 6:
			self.pad.val = (0.0, 0.0)
			self.pad.setNeedsDisplay_(True)
			self.padField.setStringValue_("0, 0")
			self.update()
			return
		sliderCtl, field, default = self._rowBySlider[tag]
		sliderCtl.setDoubleValue_(default)
		self.sliderCallback_(sender)

	def fieldChanged_(self, sender):
		raw = sender.stringValue()
		if sender is self.padField:
			try:
				parts = raw.replace("%", "").split(",")
				x = float(parts[0].strip())
				y = float(parts[1].strip()) if len(parts) > 1 else 0.0
			except (ValueError, IndexError):
				self.padChanged()  # restore display
				return
			x = max(-PAD_RANGE, min(PAD_RANGE, x))
			y = max(-PAD_RANGE, min(PAD_RANGE, y))
			self.pad.val = (x / PAD_RANGE, y / PAD_RANGE)
			self.pad.setNeedsDisplay_(True)
			self.padChanged()
			return
		for sliderCtl, field, default in self._rowBySlider:
			if sender is field:
				try:
					v = float(raw.replace("%", "").replace("+", "").strip())
				except ValueError:
					self.sliderCallback_(sender)  # restore display
					return
				v = max(sliderCtl.minValue(), min(sliderCtl.maxValue(), v))
				sliderCtl.setDoubleValue_(v)
				self.sliderCallback_(sender)
				return

	def sliderCallback_(self, sender):
		self.valueField.setStringValue_("%+d" % round(self.slider.doubleValue()))
		self.vpctField.setStringValue_("%d%%" % round(self.vpctSlider.doubleValue()))
		self.cpctField.setStringValue_("%d%%" % round(self.cpctSlider.doubleValue()))
		self.widthField.setStringValue_("%d%%" % round(self.widthSlider.doubleValue()))
		self.harmonyField.setStringValue_("%d%%" % round(self.harmonySlider.doubleValue()))
		self.balanceField.setStringValue_("%d%%" % round(self.balanceSlider.doubleValue()))
		self.update()

	# ---------------- offset engine ----------------

	@objc.python_method
	def pathSegments(self, path):
		"""Split a GSPath into segments between on-curve nodes.
		Each segment: dict with A, B (original endpoints), c1, c2 (or None),
		smoothA (original node smoothness at the segment start)."""
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
				between.append(nodes[i])
				i = (i + 1) % cnt
			A, B = nodes[a], nodes[b]
			seg = {
				'A': (A.position.x, A.position.y),
				'B': (B.position.x, B.position.y),
				'smoothA': bool(A.smooth),
				'c1': None, 'c2': None,
			}
			if len(between) == 2:
				seg['c1'] = (between[0].position.x, between[0].position.y)
				seg['c2'] = (between[1].position.x, between[1].position.y)
			elif len(between) != 0:
				return None  # quadratic or exotic: bail out for this path
			segs.append(seg)
		return segs

	@objc.python_method
	def segTangents(self, seg):
		A, B, c1, c2 = seg['A'], seg['B'], seg['c1'], seg['c2']
		if c1 is None:
			t = _unit(B[0] - A[0], B[1] - A[1])
			return t, t
		t0 = _unit(c1[0] - A[0], c1[1] - A[1]) or _unit(c2[0] - A[0], c2[1] - A[1]) or _unit(B[0] - A[0], B[1] - A[1])
		t1 = _unit(B[0] - c2[0], B[1] - c2[1]) or _unit(B[0] - c1[0], B[1] - c1[1]) or _unit(B[0] - A[0], B[1] - A[1])
		return t0, t1

	@objc.python_method
	def offsetLayerCustom(self, layer, ax, ay, counterFactor=1.0):
		"""Offset every closed path with true miter joins at corners.
		Positive = bolder. Handles lines and cubics.
		Counter paths get their offset scaled by counterFactor, so weight
		can be pushed to the outside of the letter instead of into the
		counters (RMX-style counter protection)."""
		scale = max(abs(ax), abs(ay))

		paths = []
		others = []
		for shape in layer.shapes:
			if isinstance(shape, GSPath) and shape.closed:
				paths.append(shape)
			else:
				others.append(shape)
		if not paths:
			return False

		def polyArea(pts):
			a = 0.0
			for i in range(len(pts)):
				x1, y1 = pts[i]
				x2, y2 = pts[(i + 1) % len(pts)]
				a += x1 * y2 - x2 * y1
			return a / 2.0

		# global orientation: does this font draw its outer contours CCW?
		def signedArea(path):
			return polyArea([(n.position.x, n.position.y) for n in path.nodes if n.type != OFFCURVE])

		areas = [signedArea(p) for p in paths]
		ccwOuter = areas[max(range(len(paths)), key=lambda i: abs(areas[i]))] > 0

		def normalOf(t):
			# unit normal pointing toward the white side (bold direction for +amount)
			if ccwOuter:
				return (t[1], -t[0])
			return (-t[1], t[0])

		newShapes = list(others)
		for path, origArea in zip(paths, areas):
			isCounter = (origArea > 0) != ccwOuter
			f = counterFactor if isCounter else 1.0

			def disp(t):
				n = normalOf(t)
				return (n[0] * ax * f, n[1] * ay * f)

			segs = self.pathSegments(path)
			if not segs:
				newShapes.append(path)
				continue

			# offset each segment independently
			for seg in segs:
				t0, t1 = self.segTangents(seg)
				if t0 is None or t1 is None:
					seg['oA'], seg['oB'] = seg['A'], seg['B']
					seg['t0'], seg['t1'] = (1, 0), (1, 0)
					continue
				d0, d1 = disp(t0), disp(t1)
				seg['t0'], seg['t1'] = t0, t1
				seg['oA'] = (seg['A'][0] + d0[0], seg['A'][1] + d0[1])
				seg['oB'] = (seg['B'][0] + d1[0], seg['B'][1] + d1[1])
				if seg['c1'] is not None:
					# Tiller-Hanson: offset each control-polygon edge along its
					# own normal and re-intersect, so handle lengths scale with
					# the changing curve radius (translated handles freeze the
					# curvature and produce flats/kinks)
					pts = (seg['A'], seg['c1'], seg['c2'], seg['B'])
					eT = []
					for j in range(3):
						eT.append(_unit(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1]))
					eT[0] = eT[0] or eT[1] or (t0[0], t0[1])
					eT[1] = eT[1] or eT[0]
					eT[2] = eT[2] or eT[1]
					offE = []
					for j in range(3):
						dj = disp(eT[j])
						offE.append(((pts[j][0] + dj[0], pts[j][1] + dj[1]),
							(pts[j + 1][0] + dj[0], pts[j + 1][1] + dj[1]), eT[j]))
					c1t = offE[0][1]  # translation fallback
					c2t = offE[2][0]
					h1 = _rayIntersect(offE[0][0], offE[0][2], offE[1][0], offE[1][2])
					h2 = _rayIntersect(offE[1][0], offE[1][2], offE[2][0], offE[2][2])
					c1n = h1[0] if h1 is not None else c1t
					c2n = h2[0] if h2 is not None else c2t
					if math.hypot(c1n[0] - c1t[0], c1n[1] - c1t[1]) > 4 * scale:
						c1n = c1t
					if math.hypot(c2n[0] - c2t[0], c2n[1] - c2t[1]) > 4 * scale:
						c2n = c2t
					seg['oc1'] = c1n
					seg['oc2'] = c2n

			# phase 1: decide every junction, trimming overlapped curve ends
			nsegs = len(segs)
			joins = []
			for i in range(nsegs):
				prev = segs[i - 1]
				cur = segs[i]
				E1 = prev['oB']
				E2 = cur['oA']
				P = cur['A']  # original corner position
				gap = math.hypot(E1[0] - E2[0], E1[1] - E2[1])
				bothLines = prev['c1'] is None and cur['c1'] is None

				if cur['smoothA'] or gap < WELD_EPS:
					W = ((E1[0] + E2[0]) / 2.0, (E1[1] + E2[1]) / 2.0)
					prev['oB'] = cur['oA'] = W
					joins.append(('weld', W, bool(cur['smoothA'])))
					continue

				hit = _rayIntersect(E1, prev['t1'], E2, cur['t0'])
				if hit is not None:
					M, t, s = hit
					if math.hypot(M[0] - P[0], M[1] - P[1]) <= MITER_LIMIT * scale:
						if bothLines:
							prev['oB'] = cur['oA'] = M
							joins.append(('single', M))
							continue
						if t >= -0.01 and s <= 0.01:
							# gap opens: bridge E1 -> miter point -> E2
							joins.append(('chain', E1, M, E2))
							continue
						# curve corner, edges overlap: trim both elements to
						# their actual intersection (de Casteljau split)
						pElem = ((prev['oA'], prev['oc1'], prev['oc2'], prev['oB'])
							if prev['c1'] is not None else (prev['oA'], prev['oB']))
						cElem = ((cur['oA'], cur['oc1'], cur['oc2'], cur['oB'])
							if cur['c1'] is not None else (cur['oA'], cur['oB']))
						pPts = ([_bezPt(pElem, k / 24.0) for k in range(25)]
							if len(pElem) == 4 else list(pElem))
						cPts = ([_bezPt(cElem, k / 24.0) for k in range(25)]
							if len(cElem) == 4 else list(cElem))
						x = _crossElems(pPts, cPts)
						if x is not None:
							tA, tB, X = x
							if len(pElem) == 4:
								left, _ = _bezSplit(pElem, tA)
								prev['oc1'], prev['oc2'] = left[1], left[2]
								pEnd = left[3]
							else:
								pEnd = X
							if len(cElem) == 4:
								_, right = _bezSplit(cElem, tB)
								cur['oc1'], cur['oc2'] = right[1], right[2]
								cStart = right[0]
							else:
								cStart = X
							J = ((pEnd[0] + cStart[0]) / 2.0, (pEnd[1] + cStart[1]) / 2.0)
							prev['oB'] = cur['oA'] = J
							joins.append(('single', J))
							continue
						# no crossing found: weld as fallback
						W = ((E1[0] + E2[0]) / 2.0, (E1[1] + E2[1]) / 2.0)
						prev['oB'] = cur['oA'] = W
						joins.append(('weld', W, False))
						continue
				# parallel tangents or miter too long: bevel
				joins.append(('bevel', E1, E2))

			# phase 2: emit nodes
			newNodes = []
			startNodes = []  # per segment: the joined node where it now begins
			for i in range(nsegs):
				prev = segs[i - 1]
				cur = segs[i]
				endType = CURVE if prev['c1'] is not None else LINE
				j = joins[i]
				if j[0] == 'weld':
					n = GSNode(NSMakePoint(j[1][0], j[1][1]), endType)
					n.smooth = j[2]
					newNodes.append(n)
				elif j[0] == 'single':
					# the shared endpoint after trim/miter: prev['oB'] holds it
					newNodes.append(GSNode(NSMakePoint(prev['oB'][0], prev['oB'][1]), endType))
				elif j[0] == 'chain':
					newNodes.append(GSNode(NSMakePoint(j[1][0], j[1][1]), endType))
					newNodes.append(GSNode(NSMakePoint(j[2][0], j[2][1]), LINE))
					newNodes.append(GSNode(NSMakePoint(j[3][0], j[3][1]), LINE))
				else:  # bevel
					newNodes.append(GSNode(NSMakePoint(j[1][0], j[1][1]), endType))
					newNodes.append(GSNode(NSMakePoint(j[2][0], j[2][1]), LINE))

				startNodes.append(newNodes[-1])

				if cur['c1'] is not None:
					newNodes.append(GSNode(NSMakePoint(cur['oc1'][0], cur['oc1'][1]), OFFCURVE))
					newNodes.append(GSNode(NSMakePoint(cur['oc2'][0], cur['oc2'][1]), OFFCURVE))

			# a closed path must not end mid-curve: rotate offcurves off the tail
			while newNodes and newNodes[-1].type == OFFCURVE:
				newNodes.insert(0, newNodes.pop())

			# collapse guard: when the offset exceeds a shape's local width,
			# joined segments come out running backwards (edges have passed
			# through each other). If most of the path length reversed, the
			# shape is inside out — a counter clogged shut or a stem thinned
			# past zero — so drop it instead of leaving an artifact.
			total = reversed_ = 0.0
			for i in range(nsegs):
				seg = segs[i]
				chordLen = math.hypot(seg['B'][0] - seg['A'][0], seg['B'][1] - seg['A'][1])
				if chordLen < 1e-9:
					continue
				a = startNodes[i].position
				b = startNodes[(i + 1) % nsegs].position
				dot = ((b.x - a.x) * (seg['B'][0] - seg['A'][0])
					+ (b.y - a.y) * (seg['B'][1] - seg['A'][1]))
				total += chordLen
				if dot < 0:
					reversed_ += chordLen
			if total > 0 and reversed_ > total / 2.0:
				continue

			newPath = GSPath()
			newPath.closed = True
			for n in newNodes:
				newPath.nodes.append(n)
			newShapes.append(newPath)

		layer.shapes = newShapes
		return True

	# ---------------- counter shift ----------------

	@objc.python_method
	def shiftCounters(self, layer, dx, dy):
		"""Translate counter contours (orientation opposite the dominant
		outer contour) by dx, dy."""
		if abs(dx) < 0.01 and abs(dy) < 0.01:
			return
		paths = [s for s in layer.shapes if isinstance(s, GSPath) and s.closed]
		if len(paths) < 2:
			return  # nothing that can be a counter

		def signedArea(path):
			pts = [(n.position.x, n.position.y) for n in path.nodes if n.type != OFFCURVE]
			a = 0.0
			for i in range(len(pts)):
				x1, y1 = pts[i]
				x2, y2 = pts[(i + 1) % len(pts)]
				a += x1 * y2 - x2 * y1
			return a / 2.0

		areas = [signedArea(p) for p in paths]
		ccwOuter = areas[max(range(len(paths)), key=lambda i: abs(areas[i]))] > 0
		for path, area in zip(paths, areas):
			if (area > 0) == ccwOuter:
				continue  # outer contour
			for n in path.nodes:
				p = n.position
				n.position = NSMakePoint(p.x + dx, p.y + dy)

	# ---------------- harmony / balance ----------------

	@objc.python_method
	def balanceLayer(self, layer, strength):
		"""Equalize the two handle fractions of each curve segment (each
		handle as a fraction of the distance to the tangent intersection),
		preserving endpoints and tangent directions."""
		if strength <= 0:
			return
		for path in layer.shapes:
			if not isinstance(path, GSPath):
				continue
			nodes = list(path.nodes)
			cnt = len(nodes)
			for i, n in enumerate(nodes):
				if n.type != CURVE:
					continue
				c2 = nodes[(i - 1) % cnt]
				c1 = nodes[(i - 2) % cnt]
				A = nodes[(i - 3) % cnt]
				if c1.type != OFFCURVE or c2.type != OFFCURVE or A.type == OFFCURVE:
					continue
				Ap, c1p, c2p, Bp = A.position, c1.position, c2.position, n.position
				dA = _unit(c1p.x - Ap.x, c1p.y - Ap.y)
				dB = _unit(c2p.x - Bp.x, c2p.y - Bp.y)
				if dA is None or dB is None:
					continue  # retracted handle
				hit = _rayIntersect((Ap.x, Ap.y), dA, (Bp.x, Bp.y), dB)
				if hit is None:
					continue
				T, t, s = hit
				if t < 1.0 or s < 1.0:
					continue  # inflected or degenerate: leave alone
				fa = math.hypot(c1p.x - Ap.x, c1p.y - Ap.y) / t
				fb = math.hypot(c2p.x - Bp.x, c2p.y - Bp.y) / s
				m = (fa + fb) / 2.0
				m = max(0.05, min(0.95, m))
				g1 = (Ap.x + dA[0] * m * t, Ap.y + dA[1] * m * t)
				g2 = (Bp.x + dB[0] * m * s, Bp.y + dB[1] * m * s)
				k = strength
				c1.position = NSMakePoint(c1p.x + (g1[0] - c1p.x) * k, c1p.y + (g1[1] - c1p.y) * k)
				c2.position = NSMakePoint(c2p.x + (g2[0] - c2p.x) * k, c2p.y + (g2[1] - c2p.y) * k)

	@objc.python_method
	def harmonizeLayer(self, layer, strength):
		"""Slide each smooth on-curve node between two curve segments along
		its handle line to the position where curvature is continuous (G2).
		Iterates because neighboring nodes influence each other."""
		if strength <= 0:
			return
		for _pass in range(3):
			for path in layer.shapes:
				if not isinstance(path, GSPath):
					continue
				nodes = list(path.nodes)
				cnt = len(nodes)
				for i, n in enumerate(nodes):
					if n.type != CURVE or not n.smooth:
						continue
					a2 = nodes[(i - 1) % cnt]
					a1 = nodes[(i - 2) % cnt]
					b1 = nodes[(i + 1) % cnt]
					b2 = nodes[(i + 2) % cnt]
					if (a1.type != OFFCURVE or a2.type != OFFCURVE
							or b1.type != OFFCURVE or b2.type != OFFCURVE):
						continue  # needs a curve on both sides
					P2, P1 = a2.position, a1.position
					Q1, Q2 = b1.position, b2.position
					dx, dy = Q1.x - P2.x, Q1.y - P2.y
					D = math.hypot(dx, dy)
					if D < 1e-6:
						continue
					ux, uy = dx / D, dy / D
					hIn = abs((P1.x - P2.x) * uy - (P1.y - P2.y) * ux)
					hOut = abs((Q2.x - P2.x) * uy - (Q2.y - P2.y) * ux)
					if hIn < 0.5 or hOut < 0.5:
						continue  # one side nearly straight: sliding cannot fix it
					r = math.sqrt(hIn) / (math.sqrt(hIn) + math.sqrt(hOut))
					gx, gy = P2.x + dx * r, P2.y + dy * r
					p = n.position
					k = strength
					n.position = NSMakePoint(p.x + (gx - p.x) * k, p.y + (gy - p.y) * k)

	# ---------------- filter ----------------

	@objc.python_method
	def filter(self, layer, inEditView, customParameters):
		try:
			if 'amount' in customParameters:
				amount = float(customParameters['amount'])
			else:
				amount = self.slider.doubleValue()
			if 'vertical' in customParameters:
				vpct = float(customParameters['vertical'])
			else:
				vpct = self.vpctSlider.doubleValue()
			if 'counters' in customParameters:
				cpct = float(customParameters['counters'])
			else:
				cpct = self.cpctSlider.doubleValue()
			if 'width' in customParameters:
				wpct = float(customParameters['width'])
			else:
				wpct = self.widthSlider.doubleValue()
			if 'harmony' in customParameters:
				hpct = float(customParameters['harmony'])
			else:
				hpct = self.harmonySlider.doubleValue()
			if 'balance' in customParameters:
				bpct = float(customParameters['balance'])
			else:
				bpct = self.balanceSlider.doubleValue()
			if 'countershiftx' in customParameters:
				csx = float(customParameters['countershiftx'])
			else:
				csx = self.pad.val[0] * PAD_RANGE
			if 'countershifty' in customParameters:
				csy = float(customParameters['countershifty'])
			else:
				csy = self.pad.val[1] * PAD_RANGE

			# counter shift first so the offset + overlap cleanup runs on the
			# repositioned geometry
			self.shiftCounters(layer, csx, csy)

			if abs(amount) >= 0.01:
				before = layer.bounds
				if before.size.width > 0 and before.size.height > 0:
					ax = amount
					ay = amount * vpct / 100.0
					if self.offsetLayerCustom(layer, ax, ay, cpct / 100.0):
						# boolean cleanup: corner logic only resolves adjacent
						# segments; junction spikes where non-adjacent edges
						# cross (bowl meets stem) need an overlap pass
						try:
							layer.correctPathDirection()
							layer.removeOverlap()
						except Exception:
							pass
						after = layer.bounds
						if after.size.width > 0 and after.size.height > 0:
							# restore the original bounding box: proportions preserved
							sx = before.size.width / after.size.width
							sy = before.size.height / after.size.height
							tx = before.origin.x - sx * after.origin.x
							ty = before.origin.y - sy * after.origin.y
							layer.applyTransform((sx, 0, 0, sy, tx, ty))

			# width: condense/extend outlines and advance width together
			# (floor keeps the slider's 0 end from collapsing the glyph)
			w = max(25.0, wpct) / 100.0
			if customParameters:
				# fresh layer copy per call at export time: safe to multiply
				if abs(w - 1.0) >= 0.0001:
					layer.applyTransform((w, 0, 0, 1, 0, 0))
					layer.width = layer.width * w
			else:
				# the live preview re-runs the filter on the same layer object
				# and only restores the shapes between passes, so an in-place
				# width multiply compounds on every slider event. Set the
				# width absolutely from the dialog session's cached original.
				widths = getattr(self, '_origWidths', None)
				if widths is None:
					widths = self._origWidths = {}
				orig = widths.setdefault(layer.layerId, layer.width)
				if abs(w - 1.0) >= 0.0001:
					layer.applyTransform((w, 0, 0, 1, 0, 0))
				layer.width = orig * w

			# cleanup LAST: repair what the offset and the non-uniform scales
			# did to the curves (balance evens the handles, harmony restores
			# G2 continuity at smooth joins)
			self.balanceLayer(layer, bpct / 100.0)
			self.harmonizeLayer(layer, hpct / 100.0)
		except Exception:
			print(traceback.format_exc())

	@objc.python_method
	def generateCustomParameter(self):
		return ("%s; amount:%s; vertical:%s; counters:%s; width:%s; harmony:%s; "
			"balance:%s; countershiftx:%s; countershifty:%s") % (
			self.__class__.__name__,
			round(self.slider.doubleValue()),
			round(self.vpctSlider.doubleValue()),
			round(self.cpctSlider.doubleValue()),
			round(self.widthSlider.doubleValue()),
			round(self.harmonySlider.doubleValue()),
			round(self.balanceSlider.doubleValue()),
			round(self.pad.val[0] * PAD_RANGE),
			round(self.pad.val[1] * PAD_RANGE))

	@objc.python_method
	def __file__(self):
		return __file__
