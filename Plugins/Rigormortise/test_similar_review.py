"""Synthetic outline and preview-contract tests; no installed fonts required."""
import ast,copy,json,math,sys,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
HERE=Path(__file__).resolve().parent
RES=HERE.parent/'Rigormortise.glyphsPlugin/Contents/Resources'
if not RES.exists():RES=HERE
sys.path.insert(0,str(RES))
from similar_pairs import profiles,descriptor,similarity,adjustments,parse_exclusions,reviewed_pairs,_profile_similarity
from spacing_state import initial_state,observe_changes,remember_observation
from test_similar_pairs import glyph,fixture,teach

def shifted(g,dx=0,dy=0,shear=0):
 g=copy.deepcopy(g)
 for c in g['commands']:
  for i in range(1,len(c),2):c[i]+=dx+shear*c[i+1];c[i+1]+=dy
 return g

def local_fixture():
 f=fixture();f['glyphs'].update(mark=glyph(60,60),tall=glyph(100,800))
 return f

class GeometryReviewTests(unittest.TestCase):
 def test_remote_height_does_not_change_low_mark_match(self):
  p=profiles(local_fixture());self.assertEqual(similarity(descriptor(p['a'],p['mark']),descriptor(p['tall'],p['mark'])),1)
 def test_detached_ink_is_uncertain(self):
  f=local_fixture();f['glyphs']['detached']=glyph();f['glyphs']['detached']['commands']+=shifted(glyph(100,50),dy=650)['commands'];p=profiles(f)
  self.assertEqual(similarity(descriptor(p['a'],p['mark']),descriptor(p['detached'],p['mark'])),0)
 def test_counter_does_not_count_as_detached_ink(self):
  f=local_fixture();f['glyphs']['counter']=glyph();f['glyphs']['counter']['commands']+=shifted(glyph(50,300),dx=25,dy=100)['commands'];p=profiles(f)
  self.assertEqual(p['counter']['bands'],1)
 def test_overhang_remains_uncertain(self):
  f=local_fixture();f['glyphs']['overhang']=glyph();f['glyphs']['overhang']['commands']+=shifted(glyph(400,50),dy=450)['commands'];p=profiles(f)
  self.assertLess(similarity(descriptor(p['a'],p['mark']),descriptor(p['overhang'],p['mark'])),.8)
 def test_marker_height_is_not_ignored(self):
  f=local_fixture();f['glyphs']['raised']=shifted(glyph(60,60),dy=200);p=profiles(f)
  self.assertLess(similarity(descriptor(p['a'],p['mark']),descriptor(p['a'],p['raised'])),.8)
 def test_slant_and_horizontal_origin_invariance(self):
  f=local_fixture();p=profiles(f);ref=descriptor(p['a'],p['mark']);f['slant']=18
  f['glyphs']={n:shifted(g,dx=73,shear=math.tan(math.radians(18))) for n,g in f['glyphs'].items()};p=profiles(f)
  self.assertAlmostEqual(similarity(ref,descriptor(p['a'],p['mark'])),1,places=12)
 def test_cached_matches_equal_public_score(self):
  f=local_fixture();f['glyphs']['raised']=shifted(glyph(60,60),dy=600);p=profiles(f)
  for source in [('a','mark'),('mark','raised')]:
   lesson=descriptor(p[source[0]],p[source[1]]);cache={}
   for a in p.values():
    for b in p.values():self.assertAlmostEqual(_profile_similarity(a,b,lesson,cache),similarity(descriptor(a,b),lesson),places=12)
 def test_old_descriptor_keeps_full_height_behavior(self):
  p=profiles(local_fixture());legacy={k:v for k,v in descriptor(p['a'],p['mark']).items() if k in ['leftFace','rightFace']}
  self.assertLess(similarity(descriptor(p['tall'],p['mark']),legacy),.8)
 def test_explicit_skips_and_reviewed_scope(self):
  f=fixture();s=teach(f);r=s['similarRules']['1'];r['excludedPairs']=['c\td'];self.assertNotIn('c\td',adjustments(f,s))
  r['excludedPairs']=[];r['approvedPairs']=['c\td'];self.assertEqual(set(adjustments(f,s)),{'c\td'})
  f['glyphs']['new']=glyph();self.assertEqual(set(adjustments(f,s)),{'c\td'})
  r['approvedPairs']=[];self.assertEqual(adjustments(f,s),{})
 def test_prior_approval_survives_temporary_shape_mismatch(self):
  f=fixture();s=teach(f);s['similarRules']['1']['approvedPairs']=['c\td'];f['glyphs']['c']=glyph(height=100)
  self.assertIn('c\td',reviewed_pairs(f,s))
 def test_scope_roundtrips_and_manual_zero_wins(self):
  f=fixture();s=teach(f);s['similarRules']['1']['approvedPairs']=['c\td'];s=json.loads(json.dumps(s));s['pinnedPairs']['c\td']=0
  self.assertEqual(adjustments(f,s),{})
 def test_exclusion_parser_rejects_ambiguous_or_unknown_pairs(self):
  names={'a','b','c','d'};self.assertEqual(parse_exclusions('a b, c d; a b',names),['a\tb','c\td'])
  for text in ['ab','a missing','a b c']:
   with self.assertRaises(ValueError):parse_exclusions(text,names)

# Execute the real preview/apply handlers with lightweight controls. Native UI
# rendering remains a separate check; these tests cover the mutation contract.
tree=ast.parse((RES/'rigormortise.py').read_text());controller=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name.startswith('RigormortiseController'))
methods=[]
for node in controller.body:
 if isinstance(node,ast.FunctionDef) and node.name in ['previewSimilar_','checkedSimilarDraft','applySimilar_']:
  node=copy.deepcopy(node);node.decorator_list=[];methods.append(node)
ns=dict(copy=copy,math=math,uuid=uuid,profiles=profiles,descriptor=descriptor,similarity=similarity,parse_exclusions=parse_exclusions,reviewed_pairs=reviewed_pairs,observe_changes=observe_changes,remember_observation=remember_observation,
 snapshot=lambda font,master:copy.deepcopy(font.snap),fingerprint=lambda snap:json.dumps(snap,sort_keys=True),effective_value=lambda a,b,raw,groups:raw.get(a+'\t'+b,0))
exec(compile(ast.Module(body=methods,type_ignores=[]),'<preview handlers>','exec'),ns)
class Control:
 def setEnabled_(self,v):self.enabled=v
 def setString_(self,v):self.text=v
class PreviewReviewTests(unittest.TestCase):
 def setUp(self):
  self.f=fixture();self.font=SimpleNamespace(snap=self.f,show=lambda:None);self.state=initial_state();self.state['enabled']=True;self.session={'master':'regular','state':self.state};self.config=(['a','b'],12,.9,1,'c d');self.applied=[]
  self.c=SimpleNamespace(pending=None,similarText=Control(),similarApply=Control(),similarDraft=None,similarSource=lambda:(self.font,self.session),similarConfig=lambda:self.config,refreshSimilarRules=lambda:None,apply=lambda *args:self.applied.append(args))
  self.c.similarEngine=lambda snap,state:{'pairs':{a+'\t'+b:round(adjustments(snap,state).get(a+'\t'+b,0)) for a in snap['glyphs'] for b in snap['glyphs']}}
  self.c.checkedSimilarDraft=lambda:ns['checkedSimilarDraft'](self.c)
 def preview(self):ns['previewSimilar_'](self.c,None)
 def test_preview_is_read_only_and_apply_saves_only_reviewed_keys(self):
  before=copy.deepcopy(self.state);self.preview();self.assertEqual(before,self.state);draft=self.c.similarDraft;self.assertTrue(draft)
  keys={r['key'] for r in draft['rows']};self.assertNotIn('c\td',keys);rule=list(draft['state']['similarRules'].values())[-1];self.assertEqual(set(rule['approvedPairs']),keys)
  ns['applySimilar_'](self.c,None);self.assertEqual(len(self.applied),1);self.assertEqual(self.applied[0][3],draft['state'])
 def test_previous_approvals_are_excluded(self):
  self.state.update(teach(self.f));self.state['enabled']=True;self.state['similarRules']['1']['approvedPairs']=['c\tc'];self.preview()
  self.assertNotIn('c\tc',{r['key'] for r in self.c.similarDraft['rows']})
 def test_changed_exclusion_requires_new_preview(self):
  self.preview();self.config=(*self.config[:4],'d c');ns['applySimilar_'](self.c,None);self.assertFalse(self.applied);self.assertIn('changed',self.c.similarText.text)
 def test_changed_geometry_or_state_rejects_stale_draft(self):
  self.preview();self.font.snap['glyphs']['c']=glyph(200)
  with self.assertRaises(ValueError):self.c.checkedSimilarDraft()
  self.preview();self.state['space']+=1
  with self.assertRaises(ValueError):self.c.checkedSimilarDraft()
 def test_bad_exclusion_cannot_enable_apply(self):
  self.config=(*self.config[:4],'c missing');self.preview();self.assertIsNone(self.c.similarDraft);self.assertFalse(self.c.similarApply.enabled)
if __name__=='__main__':unittest.main()
