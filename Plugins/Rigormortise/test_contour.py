"""Compiled runtime regressions against frozen, reviewed research output.
Standard-library only; requires build_engine.py. No Glyphs document writes.
"""
import copy,json,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BINARY=ROOT.parent/'Rigormortise.glyphsPlugin/Contents/Resources/rigormortise-engine'
class ContourTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.fixtures=[json.loads(p.read_text()) for p in sorted((ROOT/'testdata').glob('Saddleshoe-*.json'))]
  cls.process=subprocess.Popen([str(BINARY)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
 @classmethod
 def tearDownClass(cls):
  cls.process.terminate();cls.process.wait(timeout=5)
 def run_engine(self,request):
  self.process.stdin.write(json.dumps(request)+'\n');self.process.stdin.flush()
  result=json.loads(self.process.stdout.readline());self.assertNotIn('error',result)
  return result
 def test_stock_is_unchanged(self):
  for fixture in self.fixtures:
   result=self.run_engine(fixture['request'])
   self.assertEqual(result['metrics'],fixture['stock']['metrics'])
   self.assertEqual(result['pairs'],fixture['stock']['pairs'])
 def test_reviewed_candidate(self):
  for fixture in self.fixtures:
   req=copy.deepcopy(fixture['request']);req['contourPreset']=fixture['preset'];result=self.run_engine(req)
   self.assertEqual(result['metrics'],fixture['candidate']['metrics'])
   for key,value in fixture['candidate']['pairs'].items():
    # Three Regular pairs lie at ceil boundaries across Python/Swift doubles.
    self.assertLessEqual(abs(result['pairs'][key]-value),1,(fixture['preset'],key))
   for key in ['r\ty','r\tf','o\to']:
    self.assertEqual(result['pairs'][key],fixture['candidate']['pairs'][key])
 def test_names_are_not_predictors_and_incremental_is_exact(self):
  for fixture in self.fixtures:
   req=copy.deepcopy(fixture['request']);req['contourPreset']=fixture['preset'];full=self.run_engine(req)
   mapping={g['name']:str(i) for i,g in enumerate(req['glyphs'])}
   for g in req['glyphs']:g['name']=mapping[g['name']]
   renamed=self.run_engine(req)
   for key,value in full['pairs'].items():self.assertEqual(renamed['pairs']['\t'.join(mapping[n] for n in key.split('\t'))],value)
   req['changed']=[mapping['r']];partial=self.run_engine(req)
   expected={k:v for k,v in renamed['pairs'].items() if mapping['r'] in k.split('\t')}
   self.assertEqual(partial['pairs'],expected)
 def test_manual_bearing_is_not_cancelled(self):
  for fixture in self.fixtures:
   req=copy.deepcopy(fixture['request']);req['contourPreset']=fixture['preset'];base=self.run_engine(req)
   n=next(g for g in req['glyphs'] if g['name']=='n');n['left']=base['metrics']['n']['left']+40
   result=self.run_engine(req)
   self.assertEqual(result['metrics']['n']['left'],n['left'])
   self.assertEqual(result['pairs']['o\tn'],base['pairs']['o\tn'])
 def test_tracking_and_geometry_are_live(self):
  fixture=self.fixtures[-1];req=copy.deepcopy(fixture['request']);req['contourPreset']=fixture['preset'];base=self.run_engine(req)
  req['space']+=8;tracked=self.run_engine(req)
  self.assertNotEqual(base['metrics'],tracked['metrics'])
  glyph=next(g for g in req['glyphs'] if g['name']=='r')
  for cmd in glyph['commands']:
   for i in range(1,len(cmd),2):cmd[i]*=0.8
  glyph['shape']+='-edited';edited=self.run_engine(req)
  self.assertNotEqual(tracked['pairs']['r\tf'],edited['pairs']['r\tf'])
 def test_unknown_preset_fails_without_corrupting_worker(self):
  req=copy.deepcopy(self.fixtures[0]['request']);req['contourPreset']='unknown'
  self.process.stdin.write(json.dumps(req)+'\n');self.process.stdin.flush()
  self.assertIn('error',json.loads(self.process.stdout.readline()))
  self.run_engine(self.fixtures[0]['request'])
if __name__=='__main__':unittest.main()
