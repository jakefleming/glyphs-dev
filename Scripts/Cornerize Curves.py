# MenuTitle: Cornerize Curves
# -*- coding: utf-8 -*-
__doc__ = """
Replaces each curve segment with a corner point at the handles' tangent intersection.
Falls back to flat line segments when the intersection is too far away or behind the handles.
"""

import math
from Foundation import NSPoint
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, CURVE, OFFCURVE

MAX_FACTOR = 1.0  # corner may sit at most this * chord-length away from the segment; lower = stricter
FALLBACK_STEPS = 3  # line segments used when falling back to plain flattening


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
    # intersection must lie ahead of both handles, not behind (S-curves)
    if t < 0 or u < 0:
        return None
    return NSPoint(p0.x + t * a.x, p0.y + t * a.y)


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


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
                chord = dist(p0, p3)
                corner = tangent_intersection(p0, p1, p2, p3)
                ok = (corner is not None
                      and chord > 0
                      and min(dist(corner, p0), dist(corner, p3)) <= MAX_FACTOR * chord)
                if ok:
                    newPath.nodes.append(GSNode(corner, LINE))
                else:
                    for s in range(1, FALLBACK_STEPS):
                        newPath.nodes.append(GSNode(bez(p0, p1, p2, p3, s / float(FALLBACK_STEPS)), LINE))
                newPath.nodes.append(GSNode(p3, LINE))
            else:
                newPath.nodes.append(GSNode(n.position, LINE))
        newShapes.append(newPath)
    layer.shapes = newShapes
    layer.parent.endUndo()

Glyphs.redraw()
