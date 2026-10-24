import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'GraverSpacing.glyphsPlugin/Contents/Resources'))
from spacing_state import *
class Ownership(unittest.TestCase):
 def test_manual_delta(self):
  s=initial_state();a={'n':dict(shape='a',left=20,right=20)};b={'n':dict(shape='a',left=35,right=20)}
  detect_adjustments(s,a,b);self.assertEqual(s['overrides']['n']['left'],15)
  b['n']['shape']='b';b['n']['left']=200;detect_adjustments(s,a,b);self.assertEqual(s['overrides']['n']['left'],15)
 def test_one_unit_outline_edit_is_not_a_spacing_override(self):
  s=initial_state()
  a={'n':dict(shape='a',left=20,right=20,commands=[[0,0,0],[1,100,0]])}
  b={'n':dict(shape='b',left=21,right=20,commands=[[0,0,0],[1,99,0]])}
  detect_adjustments(s,a,b);self.assertEqual(s['overrides'],{})
 def test_deleted_pair_is_zero_pin(self):
  s=initial_state();s['managedPairs']={'A\tV':-60};update_pair_ownership(s,{})
  self.assertEqual(s['pinnedPairs'],{'A\tV':0});self.assertFalse(s['managedPairs'])
 def test_changed_pair_is_pinned(self):
  s=initial_state();s['managedPairs']={'T\to':-60};update_pair_ownership(s,{'T\to':-35})
  self.assertEqual(s['pinnedPairs'],{'T\to':-35})
 def test_authored_group_precedes_auto(self):
  groups={'T':('', '@MMK_L_T'),'o':('@MMK_R_o','')}
  raw={'T\to':-20,'@MMK_L_T\t@MMK_R_o':-70}
  self.assertEqual(effective_authored('T','o',raw,{'T\to':-20},groups),-70)
 def test_no_override_for_unchanged(self):
  s=initial_state();a={'n':dict(shape='a',left=20,right=20)};detect_adjustments(s,a,a)
  self.assertEqual(s['overrides'],{})
if __name__=='__main__':unittest.main()
