"""Storage/migration tests without importing AppKit. Native adapter checks are recorded separately."""
import ast,json,sys,unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
RESOURCE=Path(__file__).resolve().parent.parent/'GraverSpacing.glyphsPlugin/Contents/Resources'
if not RESOURCE.exists():RESOURCE=Path(__file__).resolve().parent
sys.path.insert(0,str(RESOURCE))
from spacing_state import initial_state
source=ast.parse((RESOURCE/'graver_spacing.py').read_text())
names={'KEY','MASTER_KEY','PRESETS'}
nodes=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in {'selected_master','load_state','store_state'} or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets)]
ns={'json':json,'initial_state':initial_state};exec(compile(ast.Module(body=nodes,type_ignores=[]),'<state helpers>','exec'),ns)
class MasterStateTests(unittest.TestCase):
 def setUp(self):
  self.a=SimpleNamespace(id='a',axes=[400],userData=defaultdict(lambda:None))
  self.b=SimpleNamespace(id='b',axes=[1000],userData=defaultdict(lambda:None))
  self.font=SimpleNamespace(masters=[self.a,self.b],selectedFontMaster=self.a,userData=defaultdict(lambda:None))
 def test_new_masters_stay_off(self):
  self.assertFalse(ns['load_state'](self.font,'a')['enabled']);self.assertFalse(ns['load_state'](self.font,'b')['enabled'])
 def test_legacy_ownership_migrates_once(self):
  old=initial_state(77);old.update(enabled=True,pinnedPairs={'r\tf':10})
  self.font.userData[ns['KEY']]=json.dumps(old)
  self.assertEqual(ns['load_state'](self.font,'a'),old)
  self.assertFalse(ns['load_state'](self.font,'b')['enabled']);self.assertEqual(ns['load_state'](self.font,'b')['pinnedPairs'],{})
 def test_store_targets_id_not_selection(self):
  state=initial_state(93);state['enabled']=True
  self.font.selectedFontMaster=self.b;ns['store_state'](self.font,state,'a')
  self.assertEqual(ns['load_state'](self.font,'a'),state)
  self.assertFalse(ns['load_state'](self.font,'b')['enabled'])
 def test_master_state_supersedes_legacy(self):
  old=initial_state();old['enabled']=True;self.font.userData[ns['KEY']]=json.dumps(old)
  new=initial_state(83);ns['store_state'](self.font,new,'a')
  self.assertEqual(ns['load_state'](self.font,'a'),new)
 def test_deleted_master_rejected(self):
  with self.assertRaises(ValueError):ns['store_state'](self.font,initial_state(),'deleted')
 def test_saved_master_states_independent(self):
  a=initial_state(86);a.update(enabled=True,contourPreset='saddleshoe-regular-v3',pinnedPairs={'r\tf':140})
  b=initial_state(58);b.update(contourPreset='saddleshoe-black-v3')
  ns['store_state'](self.font,a,'a');ns['store_state'](self.font,b,'b')
  self.assertEqual(ns['load_state'](self.font,'a'),a);self.assertEqual(ns['load_state'](self.font,'b'),b)
if __name__=='__main__':unittest.main()
