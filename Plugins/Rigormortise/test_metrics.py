"""Regression tests against the adapter's actual translation function, without AppKit."""
import ast,unittest
from pathlib import Path
from types import SimpleNamespace as Obj
path=Path(__file__).resolve().parent.parent/'Rigormortise.glyphsPlugin/Contents/Resources/rigormortise.py'
function=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='set_metrics')
namespace={};exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),namespace)
set_metrics=namespace['set_metrics']
class Node:
 def __init__(self,x,y):self.position=Obj(x=x,y=y)
 def setPositionFast_round_(self,point,rounded):
  assert not rounded
  self.position=Obj(x=point[0],y=point[1])
class Layer:
 def __init__(self,left):
  self.paths=[Obj(nodes=[Node(left,0.125),Node(left+12.375,680.25),Node(left+99.5,300.125)],elementDidChange_=lambda node:None)]
  self.anchors=[];self.guides=[];self.width=180
 @property
 def bounds(self):
  xs=[n.position.x for p in self.paths for n in p.nodes]
  return Obj(origin=Obj(x=min(xs)),size=Obj(width=max(xs)-min(xs)))
 def setNeedUpdateShapes(self):pass
 def setNeedUpdateMetrics(self):pass
 def updateMetrics(self):pass
 def points(self):return [(n.position.x,n.position.y) for p in self.paths for n in p.nodes]
class MetricsTests(unittest.TestCase):
 def test_half_unit_round_trip(self):
  layer=Layer(25.5);before=layer.points();width=layer.width
  right=width-layer.bounds.origin.x-layer.bounds.size.width
  set_metrics(layer,30.5,right+5)
  set_metrics(layer,25.5,right)
  self.assertEqual(layer.points(),before);self.assertEqual(layer.width,width)
 def test_repeated_adjustments_do_not_drift(self):
  for left in (25.5,26.5,-3.5,25.125,25.875):
   layer=Layer(left);before=layer.points();width=layer.width;right=width-left-layer.bounds.size.width
   for target in (30,31,50,0,-15,25):
    set_metrics(layer,target,20)
    set_metrics(layer,left,right)
    self.assertEqual(layer.points(),before);self.assertEqual(layer.width,width)
 def test_preserves_every_fractional_coordinate(self):
  layer=Layer(26.5);before=layer.points();set_metrics(layer,45,32)
  offsets=[b[0]-a[0] for a,b in zip(before,layer.points())]
  self.assertEqual(len(set(offsets)),1)
  self.assertEqual([p[1] for p in before],[p[1] for p in layer.points()])
unittest.main()
