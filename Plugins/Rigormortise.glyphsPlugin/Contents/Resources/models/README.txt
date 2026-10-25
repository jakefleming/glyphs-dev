Contour spacing models

These experimental presets add a correction to the stock spacing calculation.
They were fitted to a limited set of spacing measurements. Check their results
on your typeface; they are not calibrated for every design or units-per-em value.

Each model averages two regularized contour-kernel fits, using 240 and 400
examples. Inputs describe 81 normalized facing-edge depths, ink occupancy and
vertical extents. The output is a spacing correction in the calibration's design
units.

ContourSpacing.swift measures outlines at runtime. Glyph names identify the
inputs and results but do not determine the prediction. Calculation runs locally.
