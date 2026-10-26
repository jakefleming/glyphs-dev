# encoding: utf-8
"""Even Out: a conservative, font-aware curve-weight preview."""
import importlib.util
import os
import sys
import traceback
import objc
from AppKit import NSView, NSSlider, NSTextField, NSMakeRect
from Foundation import NSMakePoint
from GlyphsApp import Glyphs
from GlyphsApp.plugins import FilterWithDialog


def load_module(name, filename):
    spec=importlib.util.spec_from_file_location(name,os.path.join(os.path.dirname(__file__),filename))
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

engine=load_module('jake_even_out_engine','even_out.py')
adapter=load_module('jake_even_out_adapter','glyphs_adapter.py')


class EvenOut(FilterWithDialog):
    @objc.python_method
    def settings(self):
        self.menuName='Even Out (Preview)'
        self.actionButtonLabel='Apply'
        self._model=None
        self._font=None
        self._master_id=None
        view=NSView.alloc().initWithFrame_(NSMakeRect(0,0,420,190))
        def label(text,y,height=24):
            field=NSTextField.alloc().initWithFrame_(NSMakeRect(14,y,392,height))
            field.setStringValue_(text)
            field.setBezeled_(False);field.setDrawsBackground_(False)
            field.setEditable_(False);field.setSelectable_(False)
            view.addSubview_(field)
            return field
        self._summary=label('Learning from the current master…',154)
        label('Adjusts curves on selected glyphs. Stems and uncertain joins stay put.',112,38)
        self._amount_label=label('Amount: 70%',86)
        self._slider=NSSlider.alloc().initWithFrame_(NSMakeRect(14,60,392,24))
        self._slider.setMinValue_(0);self._slider.setMaxValue_(100)
        self._slider.setDoubleValue_(70);self._slider.setContinuous_(False)
        self._slider.setTarget_(self);self._slider.setAction_('amountChanged:')
        view.addSubview_(self._slider)
        self._status=label('Experimental. Preview before applying.',8,44)
        self.dialog=view

    @objc.python_method
    def start(self):
        self._model=None
        self._font=Glyphs.font
        if self._font is None:return
        master=self._font.selectedFontMaster
        self._master_id=master.id
        data=adapter.corpus(self._font,master.id)
        self._model=engine.learn(data,float(self._font.upm))
        bands=sum(len(v) for v in self._model['bands'].values())
        self._summary.setStringValue_('%d weight ranges from %d distinct outlines.' % (bands,self._model['inspected']))
        if not bands:self._status.setStringValue_('Not enough agreement to suggest corrections.')

    def amountChanged_(self,sender):
        self._amount_label.setStringValue_('Amount: %d%%' % round(self._slider.doubleValue()))
        self.update()

    @objc.python_method
    def filter(self,layer,inEditView,customParameters):
        # An export does not have a frozen, reviewed master context.
        if not inEditView or customParameters:return
        if self._model is None or Glyphs.font != self._font:return
        if layer.associatedMasterId != self._master_id:return
        try:
            data=adapter.capture(layer)
            if data is None:
                self._status.setStringValue_('Components, hints or unsupported outlines left unchanged.')
                return
            # Node selections are intentionally not interpreted as a stroke region.
            if layer.selection:
                self._status.setStringValue_('Deselect points to preview the whole glyph.')
                return
            result,report=engine.correct(data,self._model,self._slider.doubleValue()/100)
            if report['changed']:
                # Prepare every coordinate before writing to the preview layer.
                updates=[(node,NSMakePoint(n['x'],n['y'])) for path,p in zip(layer.paths,result) for node,n in zip(path.nodes,p['nodes'])]
                for node,pos in updates:node.position=pos
            self._status.setStringValue_('%s: %s' % (data['name'],report['reason']))
        except Exception:
            self._status.setStringValue_('Could not evaluate this glyph. See the Macro window.')
            print(traceback.format_exc())

    @objc.python_method
    def __file__(self):return __file__
