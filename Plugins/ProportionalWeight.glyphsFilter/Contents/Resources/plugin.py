# encoding: utf-8
from __future__ import division, print_function, unicode_literals

import objc
import math
import os
import traceback
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, CURVE, OFFCURVE
from GlyphsApp.plugins import FilterWithDialog
from AppKit import (NSView, NSSlider, NSTextField, NSMakeRect, NSFont, NSButton,
	NSColor, NSBezierPath, NSImage, NSFontAttributeName, NSForegroundColorAttributeName)
from Foundation import NSMakePoint, NSString

MITER_LIMIT = 10  # max corner extension, in multiples of the offset amount
WELD_EPS = 0.25  # endpoints closer than this are welded, not joined
PAD_RANGE = 60  # units of counter shift at full pad deflection


def _c(r, g, b):
	return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)

# lil Devil palette: flat cream panel, ink lines, one orange
CREAM = _c(0.953, 0.937, 0.902)
PAPER = _c(0.990, 0.982, 0.960)
INK = _c(0.14, 0.13, 0.12)
ORANGE = _c(0.922, 0.314, 0.027)


class PWPanel(NSView):
	"""Flat cream panel: title, section rules, mascot."""

	def drawRect_(self, rect):
		b = self.bounds()
		CREAM.set()
		NSBezierPath.fillRect_(b)
		# title
		title = NSString.stringWithString_("lil Devil")
		attrs = {NSFontAttributeName: NSFont.systemFontOfSize_weight_(32, 0.56),
			NSForegroundColorAttributeName: ORANGE}
		size = title.sizeWithAttributes_(attrs)
		title.drawAtPoint_withAttributes_(((b.size.width - size.width) / 2.0, b.size.height - 48), attrs)
		# status LED above Reset
		ORANGE.set()
		NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(541, 548, 9, 9)).fill()
		# section rules
		INK.set()
		for (x1, y, x2) in getattr(self, 'rules', []):
			p = NSBezierPath.bezierPath()
			p.moveToPoint_((x1, y))
			p.lineToPoint_((x2, y))
			p.setLineWidth_(1.2)
			p.stroke()
		# mascot
		devil = getattr(self, 'devil', None)
		devilRect = getattr(self, 'devilRect', None)
		if devil is not None and devilRect is not None:
			devil.drawInRect_fromRect_operation_fraction_(
				devilRect, ((0, 0), (0, 0)), 2, 1.0)


class ProportionalWeightPad(NSView):
	"""2D XY pad: drag the dot to shift counters. Center = no shift."""

	def acceptsFirstMouse_(self, event):
		return True

	def mouseDownCanMoveWindow(self):
		return False

	def drawRect_(self, rect):
		b = self.bounds()
		inset = 10
		PAPER.set()
		NSBezierPath.fillRect_(b)
		INK.set()
		box = NSBezierPath.bezierPathWithRect_(NSMakeRect(1, 1, b.size.width - 2, b.size.height - 2))
		box.setLineWidth_(1.5)
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
		ORANGE.set()
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


class PWKnob(NSView):
	"""TX-6 style rotary knob. Drag up/down to turn, Option-drag for fine
	control, double-click to reset. Accent arc lights when off neutral.
	Exposes doubleValue/setDoubleValue_/minValue/maxValue like NSSlider."""

	def acceptsFirstMouse_(self, event):
		return True

	def mouseDownCanMoveWindow(self):
		return False

	@objc.python_method
	def setup(self, minV, maxV, neutral, owner):
		self.minV = float(minV)
		self.maxV = float(maxV)
		self.neutral = float(neutral)
		self.val = float(neutral)
		self.owner = owner

	def doubleValue(self):
		return self.val

	def setDoubleValue_(self, v):
		self.val = max(self.minV, min(self.maxV, float(v)))
		self.setNeedsDisplay_(True)

	def minValue(self):
		return self.minV

	def maxValue(self):
		return self.maxV

	@objc.python_method
	def _angle(self, v):
		# degrees clockwise from 12 o'clock, sweep -135..+135
		frac = (v - self.minV) / (self.maxV - self.minV)
		return -135.0 + 270.0 * frac

	def drawRect_(self, rect):
		b = self.bounds()
		size = min(b.size.width, b.size.height)
		cx, cy = b.size.width / 2.0, b.size.height / 2.0
		r = size / 2.0 - 4

		PAPER.set()
		NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(cx - r, cy - r, 2 * r, 2 * r)).fill()
		INK.set()
		ring = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(cx - r, cy - r, 2 * r, 2 * r))
		ring.setLineWidth_(1.5)
		ring.stroke()

		aN = self._angle(self.neutral)
		aV = self._angle(self.val)

		# neutral tick just outside the ring
		tickRad = math.radians(90 - aN)
		INK.colorWithAlphaComponent_(0.45).set()
		tick = NSBezierPath.bezierPath()
		tick.moveToPoint_((cx + math.cos(tickRad) * (r + 1), cy + math.sin(tickRad) * (r + 1)))
		tick.lineToPoint_((cx + math.cos(tickRad) * (r + 4), cy + math.sin(tickRad) * (r + 4)))
		tick.setLineWidth_(1.5)
		tick.stroke()

		offNeutral = abs(self.val - self.neutral) > (self.maxV - self.minV) * 0.002
		if offNeutral:
			# accent arc from neutral to value
			ORANGE.set()
			arc = NSBezierPath.bezierPath()
			arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
				(cx, cy), r + 2.5, 90 - aN, 90 - aV, aV > aN)
			arc.setLineWidth_(2.5)
			arc.stroke()

		# indicator line
		(ORANGE if offNeutral else INK).set()
		rad = math.radians(90 - aV)
		ind = NSBezierPath.bezierPath()
		ind.moveToPoint_((cx + math.cos(rad) * r * 0.35, cy + math.sin(rad) * r * 0.35))
		ind.lineToPoint_((cx + math.cos(rad) * r * 0.85, cy + math.sin(rad) * r * 0.85))
		ind.setLineWidth_(2.5)
		ind.setLineCapStyle_(1)  # round
		ind.stroke()

	def mouseDown_(self, event):
		if event.clickCount() >= 2:
			self.setDoubleValue_(self.neutral)
			if getattr(self, 'owner', None) is not None:
				self.owner.knobMoved()
			return
		self._dragY = event.locationInWindow().y
		self._dragVal = self.val

	def mouseDragged_(self, event):
		dy = event.locationInWindow().y - getattr(self, '_dragY', event.locationInWindow().y)
		rng = self.maxV - self.minV
		scale = rng / 200.0
		if event.modifierFlags() & (1 << 19):  # Option: fine control
			scale /= 10.0
		self.setDoubleValue_(getattr(self, '_dragVal', self.val) + dy * scale)
		if getattr(self, 'owner', None) is not None:
			self.owner.knobMoved()


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

		view = PWPanel.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 560))
		# short underlines like the pedal; devil oversized, bleeding off the
		# right edge of the panel
		view.rules = [(12, 444, 168), (12, 272, 150), (12, 128, 335)]
		view.devilRect = NSMakeRect(430, 90, 330, 330)
		devilPath = os.path.join(os.path.dirname(__file__), "devil.svg")
		view.devil = NSImage.alloc().initWithContentsOfFile_(devilPath)

		def sectionTitle(text, y):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(12, y, 200, 14))
			f.setStringValue_(text)
			f.setBezeled_(False)
			f.setDrawsBackground_(False)
			f.setEditable_(False)
			f.setSelectable_(False)
			f.setTextColor_(INK)
			f.setFont_(NSFont.systemFontOfSize_weight_(11, 0.4))
			view.addSubview_(f)
			return f

		def knobLabel(cx, y, text):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(cx - 45, y, 90, 13))
			f.setStringValue_(text.upper())
			f.setBezeled_(False)
			f.setDrawsBackground_(False)
			f.setEditable_(False)
			f.setSelectable_(False)
			f.setAlignment_(1)  # center
			f.setTextColor_(INK.colorWithAlphaComponent_(0.75))
			f.setFont_(NSFont.systemFontOfSize_weight_(9, 0.3))
			view.addSubview_(f)
			return f

		def valueField(cx, y, initial):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(cx - 28, y, 56, 19))
			f.setStringValue_(initial)
			f.setBezeled_(False)
			f.setBordered_(False)
			f.setDrawsBackground_(False)
			f.setTextColor_(INK)
			f.setEditable_(True)
			f.setSelectable_(True)
			f.setAlignment_(1)  # center
			f.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0.23))
			f.setFocusRingType_(1)  # none; cleaner while editing
			f.setTarget_(self)
			f.setAction_("fieldChanged:")
			view.addSubview_(f)
			return f

		def knobOnly(cx, y0, size, minV, maxV, neutral):
			k = PWKnob.alloc().initWithFrame_(NSMakeRect(cx - size / 2.0, y0, size, size))
			k.setup(minV, maxV, neutral, self)
			view.addSubview_(k)
			return k

		# Reset (drag knobs vertically; Option = fine; double-click = reset)
		resetBtn = NSButton.alloc().initWithFrame_(NSMakeRect(506, 515, 80, 26))
		resetBtn.setTitle_("Reset")
		resetBtn.setBezelStyle_(1)
		resetBtn.setTarget_(self)
		resetBtn.setAction_("resetCallback:")
		view.addSubview_(resetBtn)

		# WEIGHT: big center knob, flanked by its modifiers; one shared
		# baseline for every label and value in the section
		sectionTitle("WEIGHT", 448)
		self.slider = knobOnly(250, 344, 92, -200, 200, 0)
		self.vpctSlider = knobOnly(100, 366, 48, 0, 200, 100)
		self.cpctSlider = knobOnly(400, 366, 48, 0, 200, 100)
		knobLabel(250, 326, "Weight")
		knobLabel(100, 326, "Vertical")
		knobLabel(400, 326, "Counters")
		self.valueField = valueField(250, 304, "+0")
		self.vpctField = valueField(100, 304, "100%")
		self.cpctField = valueField(400, 304, "100%")

		# SHAPE: proportions + counter pad, all in one row like the pedal
		sectionTitle("SHAPE", 276)
		self.widthSlider = knobOnly(90, 200, 48, 0, 200, 100)
		self.heightSlider = knobOnly(180, 200, 48, 0, 200, 100)
		self.tensionSlider = knobOnly(270, 200, 48, 50, 150, 100)
		knobLabel(90, 182, "Width")
		knobLabel(180, 182, "Height")
		knobLabel(270, 182, "Tension")
		self.widthField = valueField(90, 160, "100%")
		self.heightField = valueField(180, 160, "100%")
		self.tensionField = valueField(270, 160, "100%")

		self.pad = ProportionalWeightPad.alloc().initWithFrame_(NSMakeRect(327, 176, 96, 96))
		self.pad.val = (0.0, 0.0)
		self.pad.owner = self
		view.addSubview_(self.pad)
		knobLabel(375, 158, "Counters XY")
		self.padField = valueField(375, 136, "0, 0")

		# PERFECT: cleanup + geometry knobs
		sectionTitle("PERFECT", 132)
		self.harmonySlider = knobOnly(60, 56, 48, 0, 100, 0)
		self.balanceSlider = knobOnly(165, 56, 48, 0, 100, 0)
		self.snapSlider = knobOnly(270, 56, 48, 0, 100, 0)
		self.facetSlider = knobOnly(375, 56, 48, 0, 100, 0)
		self.circSlider = knobOnly(480, 56, 48, 0, 100, 0)
		for cx, txt in ((60, "Harmony"), (165, "Balance"), (270, "Snap"), (375, "Facets"), (480, "Circular")):
			knobLabel(cx, 38, txt)
		self.harmonyField = valueField(60, 16, "0%")
		self.balanceField = valueField(165, 16, "0%")
		self.snapField = valueField(270, 16, "0%")
		self.facetField = valueField(375, 16, "0%")
		self.circField = valueField(480, 16, "0%")

		# row metadata for typed input and per-row reset, keyed by tag;
		# the pad is tag 6, handled separately
		self._rowBySlider = {
			0: (self.slider, self.valueField, 0),
			1: (self.vpctSlider, self.vpctField, 100),
			2: (self.cpctSlider, self.cpctField, 100),
			3: (self.widthSlider, self.widthField, 100),
			4: (self.harmonySlider, self.harmonyField, 0),
			5: (self.balanceSlider, self.balanceField, 0),
			7: (self.heightSlider, self.heightField, 100),
			8: (self.snapSlider, self.snapField, 0),
			9: (self.facetSlider, self.facetField, 0),
			10: (self.circSlider, self.circField, 0),
			11: (self.tensionSlider, self.tensionField, 100),
		}

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
		self.heightSlider.setDoubleValue_(100)
		self.snapSlider.setDoubleValue_(0)
		self.facetSlider.setDoubleValue_(0)
		self.circSlider.setDoubleValue_(0)
		self.tensionSlider.setDoubleValue_(100)
		self.pad.val = (0.0, 0.0)
		self.pad.setNeedsDisplay_(True)
		self.padField.setStringValue_("0, 0")
		self.sliderCallback_(sender)

	@objc.python_method
	def knobMoved(self):
		self.sliderCallback_(None)

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
		for sliderCtl, field, default in self._rowBySlider.values():
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
		self.heightField.setStringValue_("%d%%" % round(self.heightSlider.doubleValue()))
		self.snapField.setStringValue_("%d%%" % round(self.snapSlider.doubleValue()))
		self.facetField.setStringValue_("%d%%" % round(self.facetSlider.doubleValue()))
		self.circField.setStringValue_("%d%%" % round(self.circSlider.doubleValue()))
		self.tensionField.setStringValue_("%d%%" % round(self.tensionSlider.doubleValue()))
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

	# ---------------- geometric perfection ----------------

	@objc.python_method
	def angleSnapLayer(self, layer, strength, grid=45.0):
		"""Rotate straight edges toward the nearest multiple of `grid`
		degrees, re-intersecting neighbors. All-line closed paths only."""
		if strength <= 0:
			return
		for path in layer.shapes:
			if not isinstance(path, GSPath) or not path.closed:
				continue
			nodes = list(path.nodes)
			if len(nodes) < 3 or any(n.type == OFFCURVE for n in nodes):
				continue
			pts = [(n.position.x, n.position.y) for n in nodes]
			cnt = len(pts)
			dirs = []
			mids = []
			for i in range(cnt):
				a, b = pts[i], pts[(i + 1) % cnt]
				ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
				snapped = round(ang / grid) * grid
				newang = math.radians(ang + (snapped - ang) * strength)
				dirs.append((math.cos(newang), math.sin(newang)))
				mids.append(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))
			newpts = []
			for i in range(cnt):
				d0, d1 = dirs[i - 1], dirs[i]
				if abs(d0[0] * d1[1] - d0[1] * d1[0]) < 1e-4:
					# adjacent edges became collinear: project onto the line
					m = mids[i - 1]
					px, py = pts[i][0] - m[0], pts[i][1] - m[1]
					dot = px * d0[0] + py * d0[1]
					newpts.append((m[0] + d0[0] * dot, m[1] + d0[1] * dot))
					continue
				hit = _rayIntersect(mids[i - 1], d0, mids[i], d1)
				if hit is not None and math.hypot(hit[0][0] - pts[i][0], hit[0][1] - pts[i][1]) < 150:
					newpts.append(hit[0])
				else:
					newpts.append(pts[i])
			for n, p in zip(nodes, newpts):
				n.position = NSMakePoint(p[0], p[1])

	@objc.python_method
	def facetEvenLayer(self, layer, strength):
		"""Even out facet chains: runs of gentle same-direction turns get
		their vertices redistributed at equal arc length. Lines only."""
		if strength <= 0:
			return
		for path in layer.shapes:
			if not isinstance(path, GSPath) or not path.closed:
				continue
			nodes = list(path.nodes)
			if len(nodes) < 5 or any(n.type == OFFCURVE for n in nodes):
				continue
			pts = [(n.position.x, n.position.y) for n in nodes]
			cnt = len(pts)
			turns = []
			for i in range(cnt):
				d0 = _unit(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
				d1 = _unit(pts[(i + 1) % cnt][0] - pts[i][0], pts[(i + 1) % cnt][1] - pts[i][1])
				if d0 is None or d1 is None:
					turns.append(None)
					continue
				cross = d0[0] * d1[1] - d0[1] * d1[0]
				dot = d0[0] * d1[0] + d0[1] * d1[1]
				turns.append(math.degrees(math.atan2(cross, dot)))

			def gentle(i):
				t = turns[i]
				return t is not None and 2.0 <= abs(t) <= 40.0

			visited = set()
			for start in range(cnt):
				if start in visited or not gentle(start):
					continue
				# grow a same-sign run around `start`
				sign = turns[start] > 0
				run = [start]
				j = (start + 1) % cnt
				while j != start and gentle(j) and (turns[j] > 0) == sign and len(run) < cnt - 2:
					run.append(j)
					j = (j + 1) % cnt
				k = (start - 1) % cnt
				while k not in run and gentle(k) and (turns[k] > 0) == sign and len(run) < cnt - 2:
					run.insert(0, k)
					k = (k - 1) % cnt
				visited.update(run)
				if len(run) < 2:
					continue
				anchorA = (run[0] - 1) % cnt
				anchorB = (run[-1] + 1) % cnt
				chain = [anchorA] + run + [anchorB]
				cpts = [pts[i] for i in chain]
				seglens = [math.hypot(cpts[i + 1][0] - cpts[i][0], cpts[i + 1][1] - cpts[i][1])
					for i in range(len(cpts) - 1)]
				total = sum(seglens)
				if total < 1e-6:
					continue
				# reposition interior vertices at even arc length
				for idx in range(1, len(chain) - 1):
					target = total * idx / (len(chain) - 1)
					acc = 0.0
					for si, sl in enumerate(seglens):
						if acc + sl >= target or si == len(seglens) - 1:
							f = (target - acc) / sl if sl > 1e-9 else 0.0
							gx = cpts[si][0] + (cpts[si + 1][0] - cpts[si][0]) * f
							gy = cpts[si][1] + (cpts[si + 1][1] - cpts[si][1]) * f
							break
						acc += sl
					vi = chain[idx]
					ox, oy = pts[vi]
					nodes[vi].position = NSMakePoint(ox + (gx - ox) * strength, oy + (gy - oy) * strength)

	@objc.python_method
	def circularizeLayer(self, layer, strength):
		"""Set each curve segment's handles to circular-arc tension
		((4/3)tan(theta/4) of the tangent-intersection distances)."""
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
					continue
				hit = _rayIntersect((Ap.x, Ap.y), dA, (Bp.x, Bp.y), dB)
				if hit is None:
					continue
				T, t, s = hit
				if t < 1.0 or s < 1.0:
					continue
				cosTheta = max(-1.0, min(1.0, dA[0] * -dB[0] + dA[1] * -dB[1]))
				theta = math.acos(cosTheta)
				if theta < 0.02:
					continue
				f = (4.0 / 3.0) * math.tan(theta / 4.0)
				g1 = (Ap.x + dA[0] * f * t, Ap.y + dA[1] * f * t)
				g2 = (Bp.x + dB[0] * f * s, Bp.y + dB[1] * f * s)
				k = strength
				c1.position = NSMakePoint(c1p.x + (g1[0] - c1p.x) * k, c1p.y + (g1[1] - c1p.y) * k)
				c2.position = NSMakePoint(c2p.x + (g2[0] - c2p.x) * k, c2p.y + (g2[1] - c2p.y) * k)

	@objc.python_method
	def tensionLayer(self, layer, factor):
		"""Scale every curve handle's length by `factor` (1.0 = unchanged).
		Longer = squarer (superellipse-ward), shorter = flatter."""
		if abs(factor - 1.0) < 0.001:
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
				Ap, Bp = A.position, n.position
				c1p, c2p = c1.position, c2.position
				c1.position = NSMakePoint(Ap.x + (c1p.x - Ap.x) * factor, Ap.y + (c1p.y - Ap.y) * factor)
				c2.position = NSMakePoint(Bp.x + (c2p.x - Bp.x) * factor, Bp.y + (c2p.y - Bp.y) * factor)

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
			if 'height' in customParameters:
				hpct = float(customParameters['height'])
			else:
				hpct = self.heightSlider.doubleValue()
			if 'anglesnap' in customParameters:
				snapPct = float(customParameters['anglesnap'])
			else:
				snapPct = self.snapSlider.doubleValue()
			if 'facets' in customParameters:
				facetPct = float(customParameters['facets'])
			else:
				facetPct = self.facetSlider.doubleValue()
			if 'circular' in customParameters:
				circPct = float(customParameters['circular'])
			else:
				circPct = self.circSlider.doubleValue()
			if 'tension' in customParameters:
				tensionPct = float(customParameters['tension'])
			else:
				tensionPct = self.tensionSlider.doubleValue()
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

			# height: scale outlines vertically around the baseline (y=0);
			# vertical metrics are font-global and stay untouched
			h = max(25.0, hpct) / 100.0
			if abs(h - 1.0) >= 0.0001:
				layer.applyTransform((1, 0, 0, h, 0, 0))

			# geometric perfection on the transformed outline
			self.angleSnapLayer(layer, snapPct / 100.0)
			self.facetEvenLayer(layer, facetPct / 100.0)
			self.circularizeLayer(layer, circPct / 100.0)
			self.tensionLayer(layer, tensionPct / 100.0)

			# cleanup LAST: repair what the offset and the non-uniform scales
			# did to the curves (balance evens the handles, harmony restores
			# G2 continuity at smooth joins)
			self.balanceLayer(layer, bpct / 100.0)
			self.harmonizeLayer(layer, hpct / 100.0)
		except Exception:
			print(traceback.format_exc())

	@objc.python_method
	def generateCustomParameter(self):
		return ("%s; amount:%s; vertical:%s; counters:%s; width:%s; height:%s; "
			"harmony:%s; balance:%s; anglesnap:%s; facets:%s; circular:%s; "
			"tension:%s; countershiftx:%s; countershifty:%s") % (
			self.__class__.__name__,
			round(self.slider.doubleValue()),
			round(self.vpctSlider.doubleValue()),
			round(self.cpctSlider.doubleValue()),
			round(self.widthSlider.doubleValue()),
			round(self.heightSlider.doubleValue()),
			round(self.harmonySlider.doubleValue()),
			round(self.balanceSlider.doubleValue()),
			round(self.snapSlider.doubleValue()),
			round(self.facetSlider.doubleValue()),
			round(self.circSlider.doubleValue()),
			round(self.tensionSlider.doubleValue()),
			round(self.pad.val[0] * PAD_RANGE),
			round(self.pad.val[1] * PAD_RANGE))

	@objc.python_method
	def __file__(self):
		return __file__
