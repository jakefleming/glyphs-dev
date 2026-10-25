import sys,unittest,copy,json
from pathlib import Path
root=Path(__file__).resolve().parent.parent/'Rigormortise.glyphsPlugin/Contents/Resources'
if not root.exists():root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
from spacing_state import initial_state,remember_baseline,remember_observation,observe_changes,adopt_spacing

def snap():
 return dict(master='regular',glyphs={'n':dict(shape='curve',left=31.25,right=47.5,width=800.75,lockLeft=False,lockRight=False)},pairs={'A\tV':-70,'@MMK_L_T\t@MMK_R_o':0})
class BaselineTests(unittest.TestCase):
 def test_baseline_is_immutable_and_survives_json(self):
  s=initial_state();a=snap();remember_baseline(s,a);expected=copy.deepcopy(s['baseline'])
  a['glyphs']['n']['left']=99;a['pairs']['A\tV']=20;remember_baseline(s,a)
  self.assertEqual(json.loads(json.dumps(s))['baseline'],expected)
 def test_adoption_retains_existing_adjustments(self):
  s=initial_state();s['overrides']={'n':{'leftMode':'delta','left':7,'rightMode':'fixed','right':47.5}}
  a=snap();remember_baseline(s,a);adopt_spacing(s,a,{'n':{'left':20,'right':47.5}})
  self.assertEqual(s['overrides']['n']['left'],18.25)
  self.assertEqual(s['overrides']['n']['rightMode'],'fixed')
  self.assertTrue(s['preserveEnrollmentMetrics']);self.assertNotIn('adoptPending',s)
 def test_linked_metrics_are_not_adopted(self):
  a=snap();a['glyphs']['n']['lockLeft']=True;s=initial_state();adopt_spacing(s,a,{'n':{'left':0,'right':0}})
  self.assertNotIn('leftMode',s['overrides']['n'])
 def test_offline_manual_bearings_survive_reload(self):
  a=snap();s=initial_state();remember_observation(s,a);s=json.loads(json.dumps(s))
  a['glyphs']['n']['left']+=17;observe_changes(s,a)
  self.assertEqual(s['overrides']['n']['left'],17)
  remember_observation(s,a);observe_changes(s,a);self.assertEqual(s['overrides']['n']['left'],17)
 def test_authored_pair_deletion_and_new_zero_are_remembered(self):
  a=snap();s=initial_state();remember_observation(s,a)
  del a['pairs']['A\tV'];a['pairs']['r\tf']=0;observe_changes(s,a)
  self.assertEqual(s['pinnedPairs'],{'A\tV':0,'r\tf':0})
 def test_class_pair_manual_change_is_remembered(self):
  a=snap();s=initial_state();remember_observation(s,a);a['pairs']['@MMK_L_T\t@MMK_R_o']=-30
  observe_changes(s,a);self.assertEqual(s['pinnedPairs']['@MMK_L_T\t@MMK_R_o'],-30)
 def test_outline_edit_is_not_a_manual_bearing_adjustment(self):
  a=snap();s=initial_state();remember_observation(s,a);a['glyphs']['n'].update(shape='newcurve',left=99)
  observe_changes(s,a);self.assertEqual(s['overrides'],{})
 def test_other_master_observation_is_ignored(self):
  a=snap();s=initial_state();remember_observation(s,a);a['master']='black';a['glyphs']['n']['left']+=100
  observe_changes(s,a);self.assertEqual(s['overrides'],{})
if __name__=='__main__':unittest.main()
