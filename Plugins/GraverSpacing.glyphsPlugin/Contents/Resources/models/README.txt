Saddleshoe contour calibration, v3 (2026-10-24)

Font-specific calibration fitted from spacing measurements. The Regular
candidate was visually reviewed; Black is the corresponding study preset.

Each model averages two regularized contour-kernel fits (240 and 400 examples).
Inputs are 81 normalized facing-edge depths, occupancy and vertical extents.
Output is an additive residual in the source font's design units. These are
font-specific calibration presets, not a universal spacing model. Glyph names
only route requests and results. New outlines are measured at runtime by
ContourSpacing.swift. No external service or additional runtime is required.
