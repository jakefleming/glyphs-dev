# MenuTitle: Flatten Curves
# -*- coding: utf-8 -*-
__doc__ = """
Removes handles and replaces each curve segment with straight line segments (STEPS per curve).
"""

from Foundation import NSPoint
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, CURVE, OFFCURVE

STEPS = 3  # line segments per curve; raise for a closer fit


def bez(p0, p1, p2, p3, t):
    mt = 1 - t
    return NSPoint(
        mt**3 * p0.x + 3 * mt**2 * t * p1.x + 3 * mt * t**2 * p2.x + t**3 * p3.x,
        mt**3 * p0.y + 3 * mt**2 * t * p1.y + 3 * mt * t**2 * p2.y + t**3 * p3.y)


for layer in Glyphs.font.selectedLayers:
    layer.parent.beginUndo()
    newShapes = []
    for shape in layer.shapes:
        if not isinstance(shape, GSPath):
            newShapes.append(shape)
            continue
        nodes = list(shape.nodes)
        newPath = GSPath()
        newPath.closed = shape.closed
        for i, n in enumerate(nodes):
            if n.type == OFFCURVE:
                continue
            if n.type == CURVE:
                p0 = nodes[i - 3].position
                p1 = nodes[i - 2].position
                p2 = nodes[i - 1].position
                p3 = n.position
                for s in range(1, STEPS):
                    newPath.nodes.append(GSNode(bez(p0, p1, p2, p3, s / float(STEPS)), LINE))
                newPath.nodes.append(GSNode(p3, LINE))
            else:
                newPath.nodes.append(GSNode(n.position, LINE))
        newShapes.append(newPath)
    layer.shapes = newShapes
    layer.parent.endUndo()

Glyphs.redraw()
