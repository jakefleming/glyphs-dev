# encoding: utf-8
from __future__ import division, print_function, unicode_literals

import objc
import traceback
from GlyphsApp import Glyphs
from GlyphsApp.plugins import FilterWithDialog
from AppKit import NSView, NSSlider, NSTextField, NSMakeRect, NSFont, NSColor
from Foundation import NSClassFromString


class ProportionalWeight(FilterWithDialog):

	@objc.python_method
	def settings(self):
		self.menuName = "Proportional Weight"
		self.actionButtonLabel = "Apply"

		view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 70))

		label = NSTextField.alloc().initWithFrame_(NSMakeRect(12, 44, 200, 17))
		label.setStringValue_("Weight")
		label.setBezeled_(False)
		label.setDrawsBackground_(False)
		label.setEditable_(False)
		label.setSelectable_(False)
		label.setFont_(NSFont.systemFontOfSize_(11))
		view.addSubview_(label)

		self.valueField = NSTextField.alloc().initWithFrame_(NSMakeRect(222, 44, 46, 17))
		self.valueField.setStringValue_("0")
		self.valueField.setBezeled_(False)
		self.valueField.setDrawsBackground_(False)
		self.valueField.setEditable_(False)
		self.valueField.setSelectable_(False)
		self.valueField.setAlignment_(2)  # right
		self.valueField.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0))
		view.addSubview_(self.valueField)

		self.slider = NSSlider.alloc().initWithFrame_(NSMakeRect(10, 14, 258, 24))
		self.slider.setMinValue_(-60)
		self.slider.setMaxValue_(60)
		self.slider.setDoubleValue_(0)
		self.slider.setContinuous_(True)
		self.slider.setTarget_(self)
		self.slider.setAction_("sliderCallback:")
		view.addSubview_(self.slider)

		self.dialog = view

	def sliderCallback_(self, sender):
		self.valueField.setStringValue_("%d" % round(self.slider.doubleValue()))
		self.update()

	@objc.python_method
	def offsetLayer(self, layer, amount):
		F = NSClassFromString("GlyphsFilterOffsetCurve")
		# signature differs across Glyphs versions; try newest first
		attempts = (
			lambda: F.offsetLayer_offsetX_offsetY_makeStroke_autoStroke_position_metrics_error_shadow_capStyleStart_capStyleEnd_keepCompatibleOutlines_(
				layer, amount, amount, False, False, 0.5, None, None, None, 0, 0, True),
			lambda: F.offsetLayer_offsetX_offsetY_makeStroke_autoStroke_position_metrics_(
				layer, amount, amount, False, False, 0.5, None),
			lambda: F.offsetLayer_offsetX_offsetY_makeStroke_autoStroke_position_error_shadow_(
				layer, amount, amount, False, False, 0.5, None, None),
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
			if abs(amount) < 0.01:
				return

			before = layer.bounds
			if before.size.width == 0 or before.size.height == 0:
				return

			if not self.offsetLayer(layer, amount):
				print("Proportional Weight: offset filter not available")
				return

			after = layer.bounds
			if after.size.width == 0 or after.size.height == 0:
				return

			# scale back so the bounding box matches the original: proportions preserved
			sx = before.size.width / after.size.width
			sy = before.size.height / after.size.height
			tx = before.origin.x - sx * after.origin.x
			ty = before.origin.y - sy * after.origin.y
			layer.applyTransform((sx, 0, 0, sy, tx, ty))
		except Exception:
			print(traceback.format_exc())

	@objc.python_method
	def generateCustomParameter(self):
		return "%s; amount:%s" % (self.__class__.__name__, round(self.slider.doubleValue()))

	@objc.python_method
	def __file__(self):
		return __file__
