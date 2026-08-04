# encoding: utf-8
from __future__ import division, print_function, unicode_literals

import objc
import traceback
from GlyphsApp import Glyphs
from GlyphsApp.plugins import FilterWithDialog
from AppKit import NSView, NSSlider, NSTextField, NSMakeRect, NSFont
from Foundation import NSClassFromString


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

			# weight: offset, then restore the original bounding box; with the
			# reduced vertical offset the y factor stays near 1, so diagonals
			# keep their angle
			if abs(amount) >= 0.01:
				before = layer.bounds
				if before.size.width > 0 and before.size.height > 0:
					if self.offsetLayer(layer, amount, amount * vpct / 100.0):
						after = layer.bounds
						if after.size.width > 0 and after.size.height > 0:
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
