# MenuTitle: Cornerize Curves…
# -*- coding: utf-8 -*-
__doc__ = """
Turn cubic curves into corners or straight segments. Prompts for a threshold
in font units and remembers it for the next run. Applies to selected layers.
"""

import math
from Foundation import NSPoint, NSMakeRect
from AppKit import NSAlert, NSTextField, NSAlertFirstButtonReturn
from GlyphsApp import Glyphs, GSPath, GSNode, LINE, CURVE, OFFCURVE

DEFAULT_THRESHOLD = 30.0
THRESHOLD_KEY = "com.jakefleming.CornerizeCurves.threshold"
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


def ask_threshold():
    Glyphs.registerDefault(THRESHOLD_KEY, DEFAULT_THRESHOLD)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Cornerize Curves")
    explanation = (
        "Threshold (font units): maximum distance from the corner to the "
        "curve's midpoint. Higher values allow more pronounced corners. "
        "Other curves become three straight segments."
    )
    alert.setInformativeText_(explanation)
    alert.addButtonWithTitle_("Apply")
    alert.addButtonWithTitle_("Cancel")
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 24))
    field.setStringValue_(str(Glyphs.defaults[THRESHOLD_KEY]))
    alert.setAccessoryView_(field)
    alert.window().setInitialFirstResponder_(field)
    while alert.runModal() == NSAlertFirstButtonReturn:
        try:
            value = float(field.stringValue().strip())
            if not math.isfinite(value) or value < 0:
                raise ValueError
        except (ValueError, OverflowError):
            alert.setInformativeText_("Enter a finite number of zero or more.\n\n" + explanation)
            continue
        Glyphs.defaults[THRESHOLD_KEY] = value
        return value
    return None


def cornerize_path(path, threshold):
    nodes = list(path.nodes)
    # Leave non-cubic paths alone, including quadratic outlines.
    if not any(n.type == CURVE for n in nodes):
        return None, 0, 0
    if any(n.type not in (LINE, CURVE, OFFCURVE) for n in nodes):
        raise ValueError("Cornerize Curves supports cubic paths only.")
    for i, node in enumerate(nodes):
        if node.type == CURVE:
            if (len(nodes) < 4 or (not path.closed and i < 3)
                    or nodes[i - 1].type != OFFCURVE
                    or nodes[i - 2].type != OFFCURVE
                    or nodes[i - 3].type == OFFCURVE):
                raise ValueError("A curve does not have two handles and a start point.")
    result = path.copy()
    result.nodes = []
    cornered = flattened = 0
    for i, node in enumerate(nodes):
        if node.type == OFFCURVE:
            continue
        if node.type == CURVE:
            p0, p1, p2 = (nodes[i - j].position for j in (3, 2, 1))
            p3 = node.position
            corner = tangent_intersection(p0, p1, p2, p3)
            if corner is not None and dist(corner, bez(p0, p1, p2, p3, 0.5)) <= threshold:
                result.nodes.append(GSNode(corner, LINE))
                cornered += 1
            else:
                for step in range(1, FALLBACK_STEPS):
                    result.nodes.append(GSNode(bez(p0, p1, p2, p3, step / float(FALLBACK_STEPS)), LINE))
                flattened += 1
        endpoint = node.copy()
        endpoint.type = LINE
        endpoint.smooth = False
        result.nodes.append(endpoint)
    return result, cornered, flattened


def main():
    font = Glyphs.font
    if font is None or not font.selectedLayers:
        print("Cornerize Curves: select one or more glyph layers first.")
        return
    layers = list(font.selectedLayers)
    threshold = ask_threshold()
    if threshold is None:
        return
    # Build replacements before touching the font, so malformed paths cannot
    # leave half of the selection converted.
    replacements = []
    cornered = flattened = 0
    for layer in layers:
        paths = []
        for index, shape in enumerate(layer.shapes):
            if not isinstance(shape, GSPath):
                continue
            result, corners, flats = cornerize_path(shape, threshold)
            if result is not None:
                paths.append((index, result))
                cornered += corners
                flattened += flats
        if paths:
            replacements.append((layer, paths))
    for layer, paths in replacements:
        layer.parent.beginUndo()
        try:
            for index, result in paths:
                layer.shapes[index] = result
        finally:
            layer.parent.endUndo()
    print("corners:", cornered, "| fallback-flattened:", flattened)
    Glyphs.redraw()


if __name__ == "__main__":
    main()
