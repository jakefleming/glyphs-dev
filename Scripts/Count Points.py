# MenuTitle: Count Points
# -*- coding: utf-8 -*-
__doc__ = """
Counts the points of the selected glyphs: on-curve nodes, handles, and the
total, per path and per layer, with a font-wide summary at the end.
Select nothing to count the whole font.
"""

from GlyphsApp import Glyphs, GSPath, OFFCURVE

font = Glyphs.font
if font is None:
	print("No font open.")
else:
	layers = list(font.selectedLayers or [])
	if not layers:
		layers = [g.layers[font.selectedFontMaster.id] for g in font.glyphs]
		scope = "whole font (master: %s)" % font.selectedFontMaster.name
	else:
		scope = "%d selected layer(s)" % len(layers)

	print("Count Points — %s" % scope)
	totOn = totOff = totPaths = 0
	worst = []
	for layer in layers:
		paths = [s for s in layer.shapes if isinstance(s, GSPath)]
		comps = len(layer.shapes) - len(paths)
		if not paths and not comps:
			continue
		on = off = 0
		lines = []
		for i, p in enumerate(paths):
			pOn = sum(1 for n in p.nodes if n.type != OFFCURVE)
			pOff = sum(1 for n in p.nodes if n.type == OFFCURVE)
			on += pOn
			off += pOff
			lines.append("    path %d: %3d points  (%d on-curve, %d handles)%s"
				% (i, pOn + pOff, pOn, pOff, "" if p.closed else "  [open]"))
		totOn += on
		totOff += off
		totPaths += len(paths)
		worst.append((on + off, layer.parent.name, layer.name))
		extra = ", %d component(s)" % comps if comps else ""
		print("  %s / %s: %d points  (%d on-curve, %d handles), %d path(s)%s"
			% (layer.parent.name, layer.name, on + off, on, off, len(paths), extra))
		if len(paths) > 1:
			for line in lines:
				print(line)

	print("  ----")
	print("  TOTAL: %d points  (%d on-curve, %d handles) across %d path(s) in %d layer(s)"
		% (totOn + totOff, totOn, totOff, totPaths, len(worst)))
	if len(worst) > 1:
		worst.sort(reverse=True)
		print("  heaviest: %s" % ", ".join("%s (%d)" % (w[1], w[0]) for w in worst[:5]))
