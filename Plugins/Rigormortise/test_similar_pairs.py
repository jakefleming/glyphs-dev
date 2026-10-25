import copy,json,sys,unittest,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
RES=HERE.parent/'Rigormortise.glyphsPlugin/Contents/Resources'
if not RES.exists():RES=HERE
sys.path.insert(0,str(RES))
from similar_pairs import profiles,descriptor,similarity,adjustments
from spacing_state import initial_state,remember_observation,observe_changes
from undo_state import state_delta,restore_state

def glyph(width=100,height=500):
 return dict(commands=[[0,0,0],[1,width,0],[1,width,height],[1,0,height],[3]],shape=str((width,height)),left=40,right=40,width=width+80)
def fixture():
 return dict(master='regular',xHeight=500,glyphs={'a':glyph(),'b':glyph(),'c':glyph(),'d':glyph()},pairs={},groups={})
def teach(snap,delta=12):
 s=initial_state();p=profiles(snap)
 s['similarRules']={'1':dict(id='1',source=['a','b'],deltaEm=delta/500,threshold=.8,strength=1,descriptor=descriptor(p['a'],p['b']))}
 return s
class SimilarTests(unittest.TestCase):
 def test_same_shapes_match_and_source_is_not_changed(self):
  f=fixture();v=adjustments(f,teach(f));self.assertEqual(v['c\td'],12);self.assertNotIn('a\tb',v)
 def test_names_are_not_features(self):
  f=fixture();s=teach(f);before=adjustments(f,s);f['glyphs']['renamed']=f['glyphs'].pop('c')
  self.assertEqual(adjustments(f,s)['renamed\td'],before['c\td'])
 def test_strength_scales_without_stacking(self):
  f=fixture();s=teach(f);s['similarRules']['1']['strength']=.5
  s['similarRules']['2']=copy.deepcopy(s['similarRules']['1']);s['similarRules']['2']['id']='2'
  self.assertEqual(adjustments(f,s)['c\td'],6)
 def test_vertical_position_and_shape_affect_similarity(self):
  f=fixture();p=profiles(f);d=descriptor(p['a'],p['b'])
  f['glyphs']['c']=glyph(height=200);q=profiles(f)
  self.assertLess(similarity(d,descriptor(q['c'],q['d'])),.8)
 def test_manual_and_class_pairs_protected(self):
  f=fixture();s=teach(f);f['pairs']={'c\td':-10};self.assertNotIn('c\td',adjustments(f,s))
  s['managedPairs']={'c\td':-10};self.assertIn('c\td',adjustments(f,s))
  s['pinnedPairs']={'c\td':-10};self.assertNotIn('c\td',adjustments(f,s))
  f['pairs']={};s['managedPairs']={};s['pinnedPairs']={'@MMK_L_C\t@MMK_R_D':0};f['groups']={'c':('', '@MMK_L_C'),'d':('@MMK_R_D','')}
  self.assertNotIn('c\td',adjustments(f,s))
 def test_manual_delta_remembered(self):
  f=fixture();s=initial_state();f['pairs']={'a\tb':-20};remember_observation(s,f)
  f['pairs']['a\tb']=-8;observe_changes(s,f);self.assertEqual(s['pairExamples']['a\tb']['delta'],12)
 def test_successive_nudges_use_total_adjustment(self):
  f=fixture();s=initial_state();f['pairs']={'a\tb':-20};remember_observation(s,f)
  for value in (-15,-10,-8):
   f['pairs']['a\tb']=value;observe_changes(s,f);remember_observation(s,f)
  self.assertEqual(s['pairExamples']['a\tb']['delta'],12)
 def test_new_exception_uses_inherited_class_value(self):
  f=fixture();f['groups']={'a':('', '@MMK_L_A'),'b':('@MMK_R_B','')};f['pairs']={'@MMK_L_A\t@MMK_R_B':-50}
  s=initial_state();remember_observation(s,f);f['pairs']['a\tb']=-38;observe_changes(s,f)
  self.assertEqual(s['pairExamples']['a\tb']['delta'],12)
 def test_outline_changes_recompute_match(self):
  f=fixture();s=teach(f);self.assertIn('c\td',adjustments(f,s))
  f['glyphs']['c']=glyph(height=100);self.assertNotIn('c\td',adjustments(f,s))
 def test_save_and_rule_removal(self):
  f=fixture();s=teach(f);saved=json.loads(json.dumps(s));self.assertEqual(adjustments(f,s),adjustments(f,saved))
  saved['similarRules'].clear();self.assertEqual(adjustments(f,saved),{})
 def test_independent_rule_undo_preserves_later_rule(self):
  a=initial_state();b=teach(fixture());c=copy.deepcopy(b);c['similarRules']['later']={'id':'later'}
  undone=restore_state(c,state_delta(a,b));self.assertEqual(undone['similarRules'],{'later':{'id':'later'}})
 def test_engine_no_rule_unchanged_and_guard_applies(self):
  f=fixture();s=teach(f)
  req=dict(glyphs=[dict(g,name=n,character=None) for n,g in f['glyphs'].items()],xHeight=500,capHeight=700,space=50,slant=0,protect=True)
  def run(r):
   p=subprocess.run([str(RES/'rigormortise-engine')],input=json.dumps(r)+'\n',text=True,capture_output=True,check=True);return json.loads(p.stdout)
  base=run(req);self.assertEqual(base,dict(base))
  empty=run(dict(req,pairAdjustments={}));self.assertEqual(base['pairs'],empty['pairs']);self.assertEqual(base['metrics'],empty['metrics'])
  loose=run(dict(req,pairAdjustments=adjustments(f,s)));self.assertEqual(loose['pairs']['c\td'],base['pairs']['c\td']+12)
  tight=run(dict(req,pairAdjustments={'c\td':-500}));self.assertGreater(tight['pairs']['c\td'],base['pairs']['c\td']-500)
  self.assertEqual(tight['metrics'],base['metrics'])
if __name__=='__main__':unittest.main()
