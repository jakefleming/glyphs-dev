# MenuTitle: Remove Shallow Points
# -*- coding: utf-8 -*-
__doc__ = """
Deletes on-curve points that deviate less than a tolerance from the straight line between their neighbors.
Only touches points between two line segments; curves are left alone.
"""

import math
from Foundation import NSPoint
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, OFFCURVE

TOL = 3  # units: max deviation from the neighbor-to-neighbor line; higher = more aggressive


def point_line_dist(p, a, b):
    ab = math.hypot(b.x - a.x, b.y - a.y)
    if ab == 0:
        return math.hypot(p.x - a.x, p.y - a.y)
    return abs((b.x - a.x) * (a.y - p.y) - (a.x - p.x) * (b.y - a.y)) / ab


removed = 0
for layer in Glyphs.font.selectedLayers:
    layer.parent.beginUndo()
    for shape in layer.shapes:
        if not isinstance(shape, GSPath):
            continue
        changed = True
        while changed:
            changed = False
            nodes = list(shape.nodes)
            count = len(nodes)
            if count < 4:
                break
            for i, n in enumerate(nodes):
                if n.type != LINE:
                    continue
                prev = nodes[(i - 1) % count]
                nxt = nodes[(i + 1) % count]
                # only between two straight segments: neighbors must be on-curve
                if prev.type == OFFCURVE or nxt.type == OFFCURVE:
                    continue
                if not shape.closed and (i == 0 or i == count - 1):
                    continue
                if point_line_dist(n.position, prev.position, nxt.position) <= TOL:
                    shape.nodes.remove(n)
                    removed += 1
                    changed = True
                    break
    layer.parent.endUndo()

print("removed:", removed, "points")
Glyphs.redraw()
