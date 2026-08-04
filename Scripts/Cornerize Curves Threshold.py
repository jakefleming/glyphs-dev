# MenuTitle: Cornerize Curves (Threshold)
# -*- coding: utf-8 -*-
__doc__ = """
Corner point at the tangent intersection, but only when it lands within a threshold.
Segments whose intersection is too far away or behind the handles get flattened instead.
"""

import math
from Foundation import NSPoint
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, CURVE, OFFCURVE

MAX_DEV = 30  # units: how far the corner may bulge beyond the actual curve; lower = stricter
FALLBACK_STEPS = 3


def bez(p0, p1, p2, p3, t):
    mt = 1 - t
    return NSPoint(
        mt**3 * p0.x + 3 * mt**2 * t * p1.x + 3 * mt * t**2 * p2.x + t**3 * p3.x,
        mt**3 * p0.y + 3 * mt**2 * t * p1.y + 3 * mt * t**2 * p2.y + t**3 * p3.y)


def tangent_intersection(p0, p1, p2, p3):
    a = NSPoint(p1.x - p0.x, p1.y - p0.y)
    b = NSPoint(p2.x - p3.x, p2.y - p3.y)
    if a.x == 0 and a.y == 0:
        a = NSPoint(p3.x - p0.x, p3.y - p0.y)
    if b.x == 0 and b.y == 0:
        b = NSPoint(p0.x - p3.x, p0.y - p3.y)
    denom = a.x * b.y - a.y * b.x
    if abs(denom) < 1e-9:
        return None
    t = ((p3.x - p0.x) * b.y - (p3.y - p0.y) * b.x) / denom
    u = ((p3.x - p0.x) * a.y - (p3.y - p0.y) * a.x) / denom
    if t < 0 or u < 0:
        return None
    return NSPoint(p0.x + t * a.x, p0.y + t * a.y)


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


cornered = 0
flattened = 0
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
                corner = tangent_intersection(p0, p1, p2, p3)
                ok = (corner is not None
                      and dist(corner, bez(p0, p1, p2, p3, 0.5)) <= MAX_DEV)
                if ok:
                    newPath.nodes.append(GSNode(corner, LINE))
                    cornered += 1
                else:
                    for s in range(1, FALLBACK_STEPS):
                        newPath.nodes.append(GSNode(bez(p0, p1, p2, p3, s / float(FALLBACK_STEPS)), LINE))
                    flattened += 1
                newPath.nodes.append(GSNode(p3, LINE))
            else:
                newPath.nodes.append(GSNode(n.position, LINE))
        newShapes.append(newPath)
    layer.shapes = newShapes
    layer.parent.endUndo()

print("corners:", cornered, "| fallback-flattened:", flattened)
Glyphs.redraw()
