import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'Rigormortise.glyphsPlugin/Contents/Resources'))
from undo_state import state_delta,restore_state,pair_delta,metric_delta
from spacing_state import initial_state
class UndoTests(unittest.TestCase):
 def test_preserves_later_edits_and_other_glyphs(self):
  a=initial_state();b=initial_state();b['overrides']={'n':{'left':17,'leftMode':'delta'}};b['managedPairs']={'n\to':10}
  current=initial_state();current['overrides']={'n':{'left':19,'leftMode':'delta'},'o':{'right':12,'rightMode':'delta'}};current['managedPairs']={'n\to':15,'o\to':7}
  out=restore_state(current,state_delta(a,b))
  self.assertEqual(out['overrides']['n']['left'],19)
  self.assertEqual(out['overrides']['o'],current['overrides']['o'])
  self.assertEqual(out['managedPairs'],current['managedPairs'])
 def test_round_trip(self):
  a=initial_state();b=initial_state(63);b['overrides']={'n':{'left':17,'leftMode':'delta'}}
  restored=restore_state(b,state_delta(a,b));self.assertEqual(restored,a)
  self.assertEqual(restore_state(a,state_delta(b,a)),b)
 def test_sparse_pair_patch(self):
  self.assertEqual(pair_delta({'a':1,'b':2},{'a':1,'c':3}),{'b':(2,None),'c':(None,3)})
 def test_metrics_excludes_outline_edits(self):
  a={'n':{'shape':'a','left':10,'right':20},'o':{'shape':'b','left':2,'right':3}}
  b={'n':{'shape':'new','left':12,'right':20},'o':{'shape':'b','left':2,'right':8}}
  self.assertEqual(metric_delta(a,b),{'o':{'shape':'b','sides':{'right':(3,8)}}})
 def test_fractional_width_is_retained_in_patch(self):
  a={'n':{'shape':'a','left':10.25,'right':20.375,'width':500.625}}
  b={'n':{'shape':'a','left':29.25,'right':20.75,'width':520.0}}
  self.assertEqual(metric_delta(a,b)['n']['width'],(500.625,520.0))
unittest.main()
