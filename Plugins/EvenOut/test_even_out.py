import copy
import math
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'EvenOut.glyphsFilter/Contents/Resources'))
import even_out as e


def ellipse(rx,ry,reverse=False,cx=300,cy=320):
    k=.5522847498
    nodes=[]
    raw=[(rx,0,'curve'),(rx,k*ry,'offcurve'),(k*rx,ry,'offcurve'),(0,ry,'curve'),(-k*rx,ry,'offcurve'),(-rx,k*ry,'offcurve'),(-rx,0,'curve'),(-rx,-k*ry,'offcurve'),(-k*rx,-ry,'offcurve'),(0,-ry,'curve'),(k*rx,-ry,'offcurve'),(rx,-k*ry,'offcurve')]
    for x,y,t in raw:nodes.append({'x':cx+x,'y':cy+(-y if reverse else y),'type':t,'smooth':t=='curve'})
    return {'closed':True,'nodes':nodes}


def ring(i=0, thickness=60):
    rx,ry=240+i*9,300+i*7
    return {'name':'ring'+str(i),'group':'lower','paths':[ellipse(rx,ry),ellipse(rx-thickness,ry-thickness,True)]}


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=[ring(i) for i in range(7)]
        cls.model=e.learn(cls.corpus)

    def test_context_and_duplicate_votes(self):
        self.assertTrue(self.model['bands'])
        g=ring();many=[dict(g,name=str(i)) for i in range(30)]
        self.assertFalse(e.learn(many)['bands'])

    def test_correct_bulge_and_preserve_nodes(self):
        bad=ring(9)
        # A displaced inner extremum creates a local thin region.
        for i in (0,1,11):bad['paths'][1]['nodes'][i]['x']+=13
        original=copy.deepcopy(bad)
        result,report=e.correct(bad,self.model)
        self.assertTrue(report['changed'],report)
        self.assertLess(report['after_error'],report['before_error'])
        self.assertEqual(original,bad)
        for a,b in zip(bad['paths'],result):
            self.assertEqual([(n['type'],n['smooth']) for n in a['nodes']],[(n['type'],n['smooth']) for n in b['nodes']])
        # Every handle still points along the original ray from its endpoint.
        before=e.segments(bad['paths']);after=e.segments(result)
        for a,b in zip(before,after):
            for t in (0,1):self.assertGreater(e.dot(e.tangent(a,t),e.tangent(b,t)),.999999)
        self.assertEqual(e.crossing_count(e.mesh(after)),0)

    def test_good_shapes_and_amount_zero_unchanged(self):
        g=ring(2)
        result,report=e.correct(g,self.model)
        self.assertFalse(report['changed'],report)
        self.assertEqual(result,g['paths'])
        result,report=e.correct(g,self.model,0)
        self.assertEqual(result,g['paths'])

    def test_distinct_weights_and_groups(self):
        other=[dict(ring(i,95),name='heavy'+str(i)) for i in range(7)]
        model=e.learn(self.corpus+other)
        self.assertTrue(any(len(b)==2 for b in model['bands'].values()))
        g=ring(2);g['group']='unrelated'
        self.assertFalse(e.correct(g,self.model)[1]['changed'])

    def test_small_corpus_and_open_contours(self):
        self.assertFalse(e.learn(self.corpus[:3])['bands'])
        g=ring();g['paths'][0]['closed']=False
        result,report=e.correct(g,self.model)
        self.assertFalse(report['changed']);self.assertEqual(result,g['paths'])

    def test_large_difference_not_forced_into_family(self):
        g=ring(1,120)
        self.assertFalse(e.correct(g,self.model)[1]['changed'])

    def test_determinism_and_amount(self):
        g=ring(9)
        for i in (0,1,11):g['paths'][1]['nodes'][i]['x']+=13
        full,r=e.correct(g,self.model)
        self.assertEqual((full,r),e.correct(g,self.model))
        half,h=e.correct(g,self.model,.5)
        self.assertTrue(h['changed'])
        self.assertLess(r['after_error'],h['after_error'])
        with self.assertRaises(ValueError):e.correct(g,self.model,float('nan'))


    def test_straight_stems_and_intersections_are_untouched(self):
        rect={'closed':True,'nodes':[{'x':x,'y':y,'type':'line','smooth':False} for x,y in ((0,0),(65,0),(65,500),(0,500))]}
        g={'name':'stem','group':'lower','paths':[rect]}
        self.assertEqual(e.correct(g,self.model)[0],g['paths'])
        crossed=copy.deepcopy(g)
        crossed['paths'][0]['nodes'][1],crossed['paths'][0]['nodes'][2]=crossed['paths'][0]['nodes'][2],crossed['paths'][0]['nodes'][1]
        result,r=e.correct(crossed,self.model)
        self.assertFalse(r['changed']);self.assertIn('Intersecting',r['reason'])

    def test_frozen_model_and_scale_invariance(self):
        g=ring(9)
        for i in (0,1,11):g['paths'][1]['nodes'][i]['x']+=13
        frozen=copy.deepcopy(self.model)
        first,_=e.correct(g,self.model)
        self.assertEqual(self.model,frozen)
        def scale(item):
            item=copy.deepcopy(item)
            for p in item['paths']:
                for n in p['nodes']:n['x']*=2;n['y']*=2
            return item
        model=e.learn([scale(g) for g in self.corpus],2000)
        second,r=e.correct(scale(g),model)
        self.assertTrue(r['changed'])
        for p,q in zip(first,second):
            for n,m in zip(p['nodes'],q['nodes']):
                self.assertAlmostEqual(n['x'],m['x']/2,places=5)
                self.assertAlmostEqual(n['y'],m['y']/2,places=5)

    def test_missing_metadata_keeps_uppercase_and_lowercase_separate(self):
        import glyphs_adapter as adapter
        from types import SimpleNamespace
        caps=SimpleNamespace(name='A',unicode='0041')
        lower=SimpleNamespace(name='a',unicode='0061')
        self.assertNotEqual(adapter.group_for(caps),adapter.group_for(lower))


if __name__=='__main__': unittest.main()
