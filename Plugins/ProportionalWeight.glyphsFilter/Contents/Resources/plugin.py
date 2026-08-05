# encoding: utf-8
from __future__ import division, print_function, unicode_literals

import objc
import math
import traceback
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, CURVE, OFFCURVE
from GlyphsApp.plugins import FilterWithDialog
from AppKit import NSView, NSSlider, NSTextField, NSMakeRect, NSFont
from Foundation import NSMakePoint

MITER_LIMIT = 10  # max corner extension, in multiples of the offset amount
WELD_EPS = 0.25  # endpoints closer than this are welded, not joined


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


class ProportionalWeight(FilterWithDialog):

	@objc.python_method
	def settings(self):
		self.menuName = "Proportional Weight"
		self.actionButtonLabel = "Apply"

		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 232))

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
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(222, y, 46, 17))
			f.setStringValue_(initial)
			f.setBezeled_(False)
			f.setDrawsBackground_(False)
			f.setEditable_(False)
			f.setSelectable_(False)
			f.setAlignment_(1)  # right-aligned on macOS
			f.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0))
			view.addSubview_(f)
			return f

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

		label("Weight", 206)
		self.valueField = valueField(206, "0")
		self.slider = slider(176, -200, 200, 0)

		label("Vertical %", 152)
		self.vpctField = valueField(152, "40")
		self.vpctSlider = slider(122, 0, 200, 40)

		label("Counters %", 98)
		self.cpctField = valueField(98, "100")
		self.cpctSlider = slider(68, 0, 150, 100)

		label("Width %", 44)
		self.widthField = valueField(44, "100")
		self.widthSlider = slider(14, 50, 200, 100)

		self.dialog = view
		self._origWidths = {}

	@objc.python_method
	def start(self):
		# new dialog session: current layer widths are the new baseline
		self._origWidths = {}

	def sliderCallback_(self, sender):
		self.valueField.setStringValue_("%d" % round(self.slider.doubleValue()))
		self.vpctField.setStringValue_("%d" % round(self.vpctSlider.doubleValue()))
		self.cpctField.setStringValue_("%d" % round(self.cpctSlider.doubleValue()))
		self.widthField.setStringValue_("%d" % round(self.widthSlider.doubleValue()))
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
					seg['oc1'] = (seg['c1'][0] + d0[0], seg['c1'][1] + d0[1])
					seg['oc2'] = (seg['c2'][0] + d1[0], seg['c2'][1] + d1[1])

			# join segments: weld smooth junctions, miter corners
			newNodes = []
			startNodes = []  # per segment: the joined node where it now begins
			nsegs = len(segs)
			for i in range(nsegs):
				prev = segs[i - 1]
				cur = segs[i]
				E1 = prev['oB']  # end of previous offset segment
				E2 = cur['oA']  # start of current offset segment
				P = cur['A']  # original corner position
				endType = CURVE if prev['c1'] is not None else LINE
				gap = math.hypot(E1[0] - E2[0], E1[1] - E2[1])

				bothLines = prev['c1'] is None and cur['c1'] is None
				if cur['smoothA'] or gap < WELD_EPS:
					W = ((E1[0] + E2[0]) / 2.0, (E1[1] + E2[1]) / 2.0)
					n = GSNode(NSMakePoint(W[0], W[1]), endType)
					n.smooth = bool(cur['smoothA'])
					newNodes.append(n)
				else:
					hit = _rayIntersect(E1, prev['t1'], E2, cur['t0'])
					mitered = False
					if hit is not None:
						M, t, s = hit
						if math.hypot(M[0] - P[0], M[1] - P[1]) <= MITER_LIMIT * scale:
							if bothLines:
								# line corners collapse to the single intersection:
								# extends edges when they gap (miter), trims them
								# when they overlap (convex corner, thinning)
								newNodes.append(GSNode(NSMakePoint(M[0], M[1]), LINE))
								mitered = True
							elif t >= -0.01 and s <= 0.01:
								# curve corner, edges gap apart: keep both curve
								# endpoints and bridge through the miter point
								newNodes.append(GSNode(NSMakePoint(E1[0], E1[1]), endType))
								newNodes.append(GSNode(NSMakePoint(M[0], M[1]), LINE))
								newNodes.append(GSNode(NSMakePoint(E2[0], E2[1]), LINE))
								mitered = True
							else:
								# curve corner, edges overlap: welding is the safe
								# trim (a real bezier trim would be better)
								W = ((E1[0] + E2[0]) / 2.0, (E1[1] + E2[1]) / 2.0)
								newNodes.append(GSNode(NSMakePoint(W[0], W[1]), endType))
								mitered = True
					if not mitered:
						# bevel fallback: straight line E1 -> E2
						newNodes.append(GSNode(NSMakePoint(E1[0], E1[1]), endType))
						newNodes.append(GSNode(NSMakePoint(E2[0], E2[1]), LINE))

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

			if abs(amount) >= 0.01:
				before = layer.bounds
				if before.size.width > 0 and before.size.height > 0:
					ax = amount
					ay = amount * vpct / 100.0
					if self.offsetLayerCustom(layer, ax, ay, cpct / 100.0):
						after = layer.bounds
						if after.size.width > 0 and after.size.height > 0:
							# restore the original bounding box: proportions preserved
							sx = before.size.width / after.size.width
							sy = before.size.height / after.size.height
							tx = before.origin.x - sx * after.origin.x
							ty = before.origin.y - sy * after.origin.y
							layer.applyTransform((sx, 0, 0, sy, tx, ty))

			# width: condense/extend outlines and advance width together
			w = wpct / 100.0
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
		except Exception:
			print(traceback.format_exc())

	@objc.python_method
	def generateCustomParameter(self):
		return "%s; amount:%s; vertical:%s; counters:%s; width:%s" % (
			self.__class__.__name__,
			round(self.slider.doubleValue()),
			round(self.vpctSlider.doubleValue()),
			round(self.cpctSlider.doubleValue()),
			round(self.widthSlider.doubleValue()))

	@objc.python_method
	def __file__(self):
		return __file__
