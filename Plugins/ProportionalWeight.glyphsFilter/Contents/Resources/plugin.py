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

		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 124))

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

		def valueField(y):
			f = NSTextField.alloc().initWithFrame_(NSMakeRect(222, y, 46, 17))
			f.setStringValue_("0")
			f.setBezeled_(False)
			f.setDrawsBackground_(False)
			f.setEditable_(False)
			f.setSelectable_(False)
			f.setAlignment_(1)  # right-aligned on macOS
			f.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0))
			view.addSubview_(f)
			return f

		label("Weight", 98)
		self.valueField = valueField(98)
		self.slider = NSSlider.alloc().initWithFrame_(NSMakeRect(10, 68, 258, 24))
		self.slider.setMinValue_(-60)
		self.slider.setMaxValue_(60)
		self.slider.setDoubleValue_(0)
		self.slider.setContinuous_(True)
		self.slider.setTarget_(self)
		self.slider.setAction_("sliderCallback:")
		view.addSubview_(self.slider)

		label("Vertical %", 44)
		self.vpctField = valueField(44)
		self.vpctField.setStringValue_("40")
		self.vpctSlider = NSSlider.alloc().initWithFrame_(NSMakeRect(10, 14, 258, 24))
		self.vpctSlider.setMinValue_(0)
		self.vpctSlider.setMaxValue_(100)
		self.vpctSlider.setDoubleValue_(40)
		self.vpctSlider.setContinuous_(True)
		self.vpctSlider.setTarget_(self)
		self.vpctSlider.setAction_("sliderCallback:")
		view.addSubview_(self.vpctSlider)

		self.dialog = view

	def sliderCallback_(self, sender):
		self.valueField.setStringValue_("%d" % round(self.slider.doubleValue()))
		self.vpctField.setStringValue_("%d" % round(self.vpctSlider.doubleValue()))
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
			if abs(amount) < 0.01:
				return

			before = layer.bounds
			if before.size.width == 0 or before.size.height == 0:
				return

			if not self.offsetLayer(layer, amount, amount * vpct / 100.0):
				print("Proportional Weight: offset filter not available")
				return

			after = layer.bounds
			if after.size.width == 0 or after.size.height == 0:
				return

			# restore the original bounding box; with the reduced vertical
			# offset the y factor stays near 1, so diagonals keep their angle
			sx = before.size.width / after.size.width
			sy = before.size.height / after.size.height
			tx = before.origin.x - sx * after.origin.x
			ty = before.origin.y - sy * after.origin.y
			layer.applyTransform((sx, 0, 0, sy, tx, ty))
		except Exception:
			print(traceback.format_exc())

	@objc.python_method
	def generateCustomParameter(self):
		return "%s; amount:%s; vertical:%s" % (
			self.__class__.__name__,
			round(self.slider.doubleValue()),
			round(self.vpctSlider.doubleValue()))

	@objc.python_method
	def __file__(self):
		return __file__
