"""Numeric editor commands and flat cubic corner regression."""
import unittest,types
from test_curse import ns,transform,mi

CAP=[(0,0,'curve',False),(5,100,'offcurve',False),(15,200,'offcurve',False),(15,300,'curve',True),(15,400,'offcurve',False),(5,500,'offcurve',False),(0,600,'curve',False),(100,600,'offcurve',False),(200,600,'offcurve',False),(300,600,'curve',True),(360,600,'offcurve',False),(400,560,'offcurve',False),(400,500,'curve',True),(400,350,'offcurve',False),(400,250,'offcurve',False),(400,100,'curve',True),(400,40,'offcurve',False),(360,0,'offcurve',False),(300,0,'curve',True)]
class Field:
    def __init__(self,s):self.s=s
    def stringValue(self):return self.s
    def setStringValue_(self,s):self.s=s
class Editor(Field):
    def string(self):return self.s
    def setString_(self,s):self.s=s
    def setSelectedRange_(self,r):self.selection=r
class Slider:
    def __init__(self,v):self.v=v
    def doubleValue(self):return self.v
    def setDoubleValue_(self,v):self.v=v
class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.p=object.__new__(ns['MakeItalic']);p=self.p
        p._angle=12;p.angleField=Field('12°');p.balanceField=Field('100%');p.uprightField=Field('0%')
        p.balanceSlider=Slider(100);p.uprightSlider=Slider(0)
        p._values={'curve':100.,'diagonal':100.,'stem':0.,'terminals':0.}
        p._fields={k:Field(str(v)) for k,v in p._values.items()};p.updates=0
        p.update=lambda:setattr(p,'updates',p.updates+1)
        ns['NSEvent'].modifierFlags=staticmethod(lambda:0)
    def test_all_fields_step_and_shift_step(self):
        for field in [self.p.angleField,self.p.balanceField,self.p.uprightField]+list(self.p._fields.values()):
            editor=Editor('20')
            self.assertTrue(self.p.control_textView_doCommandBySelector_(field,editor,'moveUp:'))
            self.assertEqual(float(editor.s.rstrip('°%')),21)
            self.p.control_textView_doCommandBySelector_(field,editor,'moveDownAndModifySelection:')
            self.assertEqual(float(editor.s.rstrip('°%')),11)
    def test_live_editor_value_and_shift_modifier(self):
        ns['NSEvent'].modifierFlags=staticmethod(lambda:1<<17)
        editor=Editor('2.5°');self.p.control_textView_doCommandBySelector_(self.p.angleField,editor,'moveUp:')
        self.assertEqual(self.p._angle,12.5)
    def test_clamping_and_unhandled_commands(self):
        for field,text,command,expected in [(self.p.angleField,'34','moveUpAndModifySelection:',35),(self.p.uprightField,'0','moveDown:',0),(self.p._fields['curve'],'149','moveUpAndModifySelection:',150),(self.p._fields['terminals'],'99','moveUpAndModifySelection:',100)]:
            editor=Editor(text);self.p.control_textView_doCommandBySelector_(field,editor,command)
            self.assertEqual(float(editor.s.rstrip('°%')),expected)
        for command,text in [('moveLeft:','12'),('moveUp:','nan'),('moveDown:','oops')]:
            self.assertFalse(self.p.control_textView_doCommandBySelector_(self.p.angleField,Editor(text),command))
class FlatCornerTests(unittest.TestCase):
    def test_flat_cubic_cap_and_baseline_preserved(self):
        for path in (CAP,list(reversed(CAP))):
            for angle in (-24,-12,12,24):
                out=transform([path],angle=angle)[0]
                self.assertEqual([n[2:] for n in path],[n[2:] for n in out])
                for before,after in zip(path,out):
                    if before[1] in (0,600):self.assertEqual(after[1],before[1])

if __name__=='__main__':unittest.main()
