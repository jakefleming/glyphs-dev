"""Synthetic upright-bowl fixtures; no private font outlines."""
import unittest, math
import types
from test_curse import polygon, ellipse, ring, Layer, build, mi, output, transform, ns, sanity

BOX=[polygon([(0,0),(500,0),(500,500),(0,500)]),polygon([(100,100),(100,400),(400,400),(400,100)])]
OPEN=[polygon([(0,500),(0,0),(500,0),(500,500),(400,500),(400,100),(100,100),(100,500)])]
MULTI=[polygon([(0,0),(500,0),(500,900),(0,900)]),polygon([(100,100),(100,400),(400,400),(400,100)]),polygon([(100,500),(100,800),(400,800),(400,500)])]
TIGHT=[ellipse(),ellipse(rx=240,ry=230,reverse=True)]
FIXTURES={'Box':BOX,'Round':ring(),'Open bowl':OPEN,'Multiple':MULTI,'Tight':TIGHT}

def upright(paths,value,angle=12):
    layer=Layer(build(paths),500);layer.width=600
    mi.italicize(layer,angle,1,0,1,0,False,value)
    assert layer.width==600
    return output(layer)

class UprightTests(unittest.TestCase):
    def test_zero_exactly_matches_existing(self):
        for name,p in FIXTURES.items():
            for angle in (-24,12,24):
                self.assertEqual(transform(p,angle=angle),upright(p,0,angle),name)
    def test_detection(self):
        for name,p in FIXTURES.items():
            self.assertTrue(ns['_bowl_regions']([[n[:2] for n in c] for c in p],[[n[2] for n in c] for c in p]),name)
    def test_box_orientation_and_intermediate(self):
        for angle in (-12,12):
            a,b,c=[upright(BOX,v,angle) for v in (0,.5,1)]
            self.assertAlmostEqual(c[1][0][0],c[1][1][0],places=7)
            for pa,pb,pc in zip(a,b,c):
                for na,nb,nc in zip(pa,pb,pc):
                    self.assertAlmostEqual(nb[0],(na[0]+nc[0])/2,places=7)
    def test_surrounding_structure_keeps_slant(self):
        result=upright(BOX,1)
        self.assertGreater(result[0][3][0]-result[0][0][0],80)
        for path in upright(MULTI,1)[1:]:
            self.assertAlmostEqual(path[0][0],path[1][0],places=6)
    def test_slider_changes_continuously(self):
        for source in (BOX,MULTI,OPEN,ring()):
            for v in (.2,.5,.8):
                a,b=upright(source,v),upright(source,v+.001)
                self.assertLess(max(abs(x[0]-y[0]) for p,q in zip(a,b) for x,y in zip(p,q)),1.)

    def test_round_bowl_is_not_unsheared_twice(self):
        for angle in (-12,12):
            result=upright(ring(),1,angle)[0]
            self.assertAlmostEqual(result[3][0],result[9][0],places=6)
    def test_both_stacked_counters_detected(self):
        self.assertEqual(len(ns['_bowl_regions']([[n[:2] for n in c] for c in MULTI],[[n[2] for n in c] for c in MULTI])),2)

    def test_topology_smoothness_and_signed_slants(self):
        for name,p in FIXTURES.items():
            for angle in (-24,12,24):
                for value in (.25,.5,1):
                    result=upright(p,value,angle)
                    self.assertEqual([[n[2:] for n in c] for c in result],[[n[2:] for n in c] for c in p])
                    self.assertEqual(sanity(result)['kinks'],0,name)
                    poly=[ns['_outline_points']([n[:2] for n in c],[n[2] for n in c]) for c in result]
                    before=[ns['_outline_points']([n[:2] for n in c],[n[2] for n in c]) for c in p]
                    self.assertEqual(ns['_outline_crossings'](poly),0,name)
                    self.assertEqual(ns['_outline_signature'](poly),ns['_outline_signature'](before),name)
    def test_unconnected_stems_unchanged(self):
        p=[polygon([(0,0),(100,0),(100,500),(0,500)]),polygon([(400,0),(500,0),(500,500),(400,500)])]
        self.assertEqual(upright(p,0),upright(p,1))
    def test_export_and_zero_balance(self):
        layer=Layer(build(BOX),500)
        mi.filter(layer,False,{'angle':12,'upright':100})
        self.assertEqual(output(layer),upright(BOX,1))
        mi._values={'curve':100.,'terminals':0.,'diagonal':100.,'stem':0.}
        mi.balanceSlider=types.SimpleNamespace(doubleValue=lambda:0.)
        mi.uprightSlider=types.SimpleNamespace(doubleValue=lambda:100.)
        mi._angle=12
        try:
            layer=Layer(build(BOX),500);mi.filter(layer,True,{})
            self.assertEqual(output(layer),transform(BOX,curve=0,diag=0))
        finally:
            del mi.balanceSlider;del mi.uprightSlider;del mi._values

if __name__=='__main__':unittest.main()
