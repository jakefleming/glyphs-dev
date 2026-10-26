"""Slanted spacing from synthetic outlines and disposable layer copies."""
import math, unittest, types
from test_curse import ns, mi, Layer, build, output, transform, polygon, ellipse
from test_upright import FIXTURES
import test_controls
from test_controls import Slider

bounds=ns['_slanted_bounds']

def run(source, spacing=0., angle=24., width=600., **options):
    layer=Layer(build(source),500);layer.width=width
    layer.anchors=[types.SimpleNamespace(position=ns['NSMakePoint'](230.,500.))]
    mi.italicize(layer,angle,options.get('curve',1.),0.,options.get('diag',1.),options.get('stem',1.),False,options.get('upright',.5),spacing)
    return layer

class SpacingTests(unittest.TestCase):
    def test_exact_cubic_bounds_exclude_handles(self):
        # x(t) has a 225-unit maximum even though the handles reach 300.
        path=[(0,0,'line',False),(300,0,'offcurve',False),(300,100,'offcurve',False),(0,100,'curve',False)]
        self.assertEqual(bounds(build([path])),(0.,225.))
    def test_full_spacing_preserves_both_slanted_sidebearings(self):
        changed=False
        for source in FIXTURES.values():
            original=bounds(build(source))
            for angle in (-24.,12.,24.):
                layer=run(source,1.,angle)
                lo,hi=bounds(layer.shapes,math.tan(math.radians(angle)),250.)
                self.assertAlmostEqual(lo,original[0],places=7)
                self.assertAlmostEqual(layer.width-hi,600.-original[1],places=7)
                changed |= abs(layer.width-600.)>1.
        self.assertTrue(changed)
    def test_intermediate_is_rigid_translation_and_width_blend(self):
        for source in FIXTURES.values():
            a,b,c=[run(source,v) for v in (0.,.5,1.)]
            self.assertAlmostEqual(b.width,(a.width+c.width)/2.)
            shifts=[]
            for pa,pb,pc in zip(output(a),output(b),output(c)):
                for na,nb,nc in zip(pa,pb,pc):
                    self.assertEqual(na[1:],nc[1:])
                    self.assertAlmostEqual(nb[0],(na[0]+nc[0])/2.)
                    shifts.append(nc[0]-na[0])
            self.assertLess(max(shifts)-min(shifts),1e-8)
            self.assertAlmostEqual(c.anchors[0].position.x-a.anchors[0].position.x,shifts[0])
    def test_zero_matches_existing_and_pure_shear_needs_no_spacing(self):
        for source in FIXTURES.values():
            layer=run(source,0.,upright=0.,stem=0.)
            self.assertEqual(output(layer),transform(source,angle=24.))
            self.assertEqual(layer.width,600.)
            a,b=[run(source,v,curve=0.,diag=0.,stem=0.,upright=0.) for v in (0.,1.)]
            self.assertEqual(output(a),output(b));self.assertEqual(a.width,b.width)
    def test_spaces_marks_and_open_paths_keep_width(self):
        for source,width in [([],500.),([ellipse()],0.)]:
            a,b=[run(source,v,width=width) for v in (0.,1.)]
            self.assertEqual(output(a),output(b));self.assertEqual(b.width,width)
        layer=Layer(build([polygon([(0,0),(100,0),(100,500),(0,500)])]),500)
        layer.width=400.;layer.shapes[0].closed=False
        mi.italicize(layer,24,1,0,1,1,False,1,1)
        self.assertEqual(layer.width,400.)
    def test_no_negative_advance(self):
        layer=Layer(build([polygon([(0,0),(10,0),(10,10),(0,10)])]),500)
        layer.width=1.
        before=output(layer)
        ns['_compensate_spacing'](layer,layer.shapes,(0.,1000.),1.,0.,250.,1.)
        self.assertEqual(layer.width,1.);self.assertEqual(output(layer),before)
    def test_export_matches_ui_and_zero_balance(self):
        p=test_controls.ControlsTests();p.setUp();ui=p.p
        ui._angle=24.;ui.spacingSlider=Slider(100);ui.uprightSlider=Slider(50)
        ui._values['stem']=100.
        ui.vertCheck=types.SimpleNamespace(state=lambda:0)
        text=ui.generateCustomParameter()
        params={k:float(v) for k,v in (entry.strip().split(':') for entry in text.split(';')[1:])}
        self.assertEqual(params['spacing'],100.)
        for source in FIXTURES.values():
            a,b=[Layer(build(source),500) for _ in range(2)]
            a.width=b.width=600.
            ui.filter(a,True,{});ui.filter(b,False,params)
            self.assertEqual(output(a),output(b));self.assertEqual(a.width,b.width)
        ui.balanceSlider=Slider(0)
        self.assertIn('spacing:0',ui.generateCustomParameter())
        layer=Layer(build(FIXTURES['Box']),500);layer.width=600.
        ui.filter(layer,True,{})
        self.assertEqual(layer.width,600.)
        self.assertEqual(output(layer),transform(FIXTURES['Box'],angle=24.,curve=0.,diag=0.))
    def test_invalid_spacing_rejected_before_mutation(self):
        layer=Layer(build(FIXTURES['Box']),500);layer.width=600.;before=output(layer)
        with self.assertRaises(ValueError):mi.filter(layer,False,{'spacing':float('nan')})
        self.assertEqual(output(layer),before);self.assertEqual(layer.width,600.)

if __name__=='__main__':unittest.main()
