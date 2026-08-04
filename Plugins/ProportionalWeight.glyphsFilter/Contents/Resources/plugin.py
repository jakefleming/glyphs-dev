# encoding: utf-8
from __future__ import division, print_function, unicode_literals

import objc
import math
import traceback
from GlyphsApp import Glyphs, OFFCURVE
from GlyphsApp.plugins import FilterWithDialog
from AppKit import NSView, NSSlider, NSTextField, NSMakeRect, NSFont
from Foundation import NSClassFromString, NSMakePoint

MITER_LIMIT = 10  # max corner extension, in multiples of the offset amount
MIN_TURN_SIN = 0.14  # ~8 degrees: below this a node is not treated as a corner


def _unit(dx, dy):
	l = math.hypot(dx, dy)
	if l < 1e-9:
		return None
	return (dx / l, dy / l)


def _lineIntersect(P, d1, Q, d2):
	denom = d1[0] * d2[1] - d1[1] * d2[0]
	if abs(denom) < 1e-9:
		return None
	t = ((Q[0] - P[0]) * d2[1] - (Q[1] - P[1]) * d2[0]) / denom
	return (P[0] + t * d1[0], P[1] + t * d1[1])


class ProportionalWeight(FilterWithDialog):

	@objc.python_method
	def settings(self):
		self.menuName = "Proportional Weight"
		self.actionButtonLabel = "Apply"

		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 178))

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

		label("Weight", 152)
		self.valueField = valueField(152, "0")
		self.slider = slider(122, -200, 200, 0)

		label("Vertical %", 98)
		self.vpctField = valueField(98, "40")
		self.vpctSlider = slider(68, 0, 200, 40)

		label("Width %", 44)
		self.widthField = valueField(44, "100")
		self.widthSlider = slider(14, 50, 200, 100)

		self.dialog = view

	def sliderCallback_(self, sender):
		self.valueField.setStringValue_("%d" % round(self.slider.doubleValue()))
		self.vpctField.setStringValue_("%d" % round(self.vpctSlider.doubleValue()))
		self.widthField.setStringValue_("%d" % round(self.widthSlider.doubleValue()))
		self.update()

	@objc.python_method
	def offsetLayer(self, layer, xAmount, yAmount):
		F = NSClassFromString("GlyphsFilterOffsetCurve")
		attempts = (
			lambda: F.offsetLayer_offsetX_offsetY_makeStroke_autoStroke_position_metrics_error_shadow_capStyleStart_capStyleEnd_keepCompatibleOutlines_(
				layer, xAmount, yAmount, False, False, 0.5, None, None, None, 0, 0, True),
			lambda: F.offsetLayer_offsetX_offsetY_makeStroke_autoStroke_position_metrics_(
				layer, xAmount, yAmount, False, False, 0.5, None),
			lambda: F.offsetLayer_offsetX_offsetY_makeStroke_autoStroke_position_error_shadow_(
				layer, xAmount, yAmount, False, False, 0.5, None, None),
		)
		for attempt in attempts:
			try:
				attempt()
				return True
			except Exception:
				continue
		return False

	@objc.python_method
	def collectCorners(self, layer):
		"""Every non-smooth on-curve node with its unit tangents in and out.
		Tangents come from handles on curves, neighbor points on lines."""
		corners = []
		for shape in layer.shapes:
			if not shape.__class__.__name__.endswith("Path"):
				continue
			nodes = list(shape.nodes)
			cnt = len(nodes)
			if cnt < 3:
				continue
			for i, n in enumerate(nodes):
				if n.type == OFFCURVE or n.smooth:
					continue
				if not shape.closed and (i == 0 or i == cnt - 1):
					continue
				p = n.position
				pp = nodes[(i - 1) % cnt].position
				if abs(pp.x - p.x) < 1e-6 and abs(pp.y - p.y) < 1e-6:
					pp = nodes[(i - 2) % cnt].position  # retracted handle
				tin = _unit(p.x - pp.x, p.y - pp.y)
				np_ = nodes[(i + 1) % cnt].position
				if abs(np_.x - p.x) < 1e-6 and abs(np_.y - p.y) < 1e-6:
					np_ = nodes[(i + 2) % cnt].position
				tout = _unit(np_.x - p.x, np_.y - p.y)
				if tin is None or tout is None:
					continue
				cross = tin[0] * tout[1] - tin[1] * tout[0]
				dot = tin[0] * tout[0] + tin[1] * tout[1]
				if abs(cross) < MIN_TURN_SIN and dot > 0:
					continue  # nearly straight-through, not a corner
				corners.append((p.x, p.y, tin, tout))
		return corners

	@objc.python_method
	def restoreCorners(self, layer, corners, ax, ay):
		"""Pull each clipped corner in the offset result out to the true miter:
		the intersection of the two tangent lines shifted by the offset."""
		scale = max(abs(ax), abs(ay))
		if scale < 0.01:
			return
		searchR = 2.5 * scale + 2

		allNodes = []
		for shape in layer.shapes:
			if not shape.__class__.__name__.endswith("Path"):
				continue
			for n in shape.nodes:
				if n.type != OFFCURVE:
					allNodes.append(n)

		for (px, py, tin, tout) in corners:
			# both possible offset sides; the result outline tells us which is right
			candidates = []
			for sign in (1.0, -1.0):
				nin = (tin[1] * sign, -tin[0] * sign)
				nout = (tout[1] * sign, -tout[0] * sign)
				A = (px + nin[0] * ax, py + nin[1] * ay)
				B = (px + nout[0] * ax, py + nout[1] * ay)
				M = _lineIntersect(A, tin, B, tout)
				if M is not None:
					candidates.append(M)
			if not candidates:
				continue

			nearest = None
			nearestDist = searchR
			for n in allNodes:
				d = math.hypot(n.position.x - px, n.position.y - py)
				if d < nearestDist:
					nearest = n
					nearestDist = d
			if nearest is None:
				continue

			M = min(candidates, key=lambda m: (m[0] - nearest.position.x) ** 2 + (m[1] - nearest.position.y) ** 2)
			if math.hypot(M[0] - px, M[1] - py) > MITER_LIMIT * scale:
				continue  # miter limit: leave the clipped corner alone
			nearest.position = NSMakePoint(M[0], M[1])
			nearest.smooth = False

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
			if 'width' in customParameters:
				wpct = float(customParameters['width'])
			else:
				wpct = self.widthSlider.doubleValue()

			if abs(amount) >= 0.01:
				before = layer.bounds
				if before.size.width > 0 and before.size.height > 0:
					ax = amount
					ay = amount * vpct / 100.0
					corners = self.collectCorners(layer)
					if self.offsetLayer(layer, ax, ay):
						self.restoreCorners(layer, corners, ax, ay)
						after = layer.bounds
						if after.size.width > 0 and after.size.height > 0:
							# restore the original bounding box; proportions preserved
							sx = before.size.width / after.size.width
							sy = before.size.height / after.size.height
							tx = before.origin.x - sx * after.origin.x
							ty = before.origin.y - sy * after.origin.y
							layer.applyTransform((sx, 0, 0, sy, tx, ty))
					else:
						print("Proportional Weight: offset filter not available")

			# width: condense/extend outlines and advance width together
			if abs(wpct - 100.0) >= 0.01:
				w = wpct / 100.0
				layer.applyTransform((w, 0, 0, 1, 0, 0))
				layer.width = layer.width * w
		except Exception:
			print(traceback.format_exc())

	@objc.python_method
	def generateCustomParameter(self):
		return "%s; amount:%s; vertical:%s; width:%s" % (
			self.__class__.__name__,
			round(self.slider.doubleValue()),
			round(self.vpctSlider.doubleValue()),
			round(self.widthSlider.doubleValue()))

	@objc.python_method
	def __file__(self):
		return __file__
