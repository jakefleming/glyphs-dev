# encoding: utf-8
import os, sys, objc, json
from GlyphsApp.plugins import GeneralPlugin
resource=os.path.dirname(__file__)
if resource not in sys.path:sys.path.insert(0,resource)
from rigormortise import RigormortiseController
class Rigormortise(GeneralPlugin):
    @objc.python_method
    def settings(self):self.name='Rigormortise'
    @objc.python_method
    def start(self):
        with open(os.path.join(resource,'validation.json')) as stream:
            validated=json.load(stream).get('passed',False)
        if not validated:
            print('Rigormortise: build is awaiting native validation; automatic startup disabled.')
            return
        self.controller=RigormortiseController.alloc().init();self.controller.start()
    @objc.python_method
    def __file__(self):return __file__
