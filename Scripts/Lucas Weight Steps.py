# MenuTitle: Lucas Weight Steps
# -*- coding: utf-8 -*-
__doc__ = """
Prints geometrically spaced stem widths from CURRENT_STEM to TARGET_STEM
(Lucas de Groot's interpolation theory: equal growth percentage per step,
not equal units), with the matching Proportional Weight custom parameter
for each instance.
"""

CURRENT_STEM = 88.0  # measured vertical stem of the master the filter runs on
TARGET_STEM = 220.0  # stem of the heaviest (or thinnest) style you want
STEPS = 4  # number of new styles up to and including the target
VERTICAL = 40  # passed through to the Proportional Weight parameter
COUNTERS = 100
WIDTH = 100

# each offset step moves both edges of a stem, so the filter amount
# is half the stem delta
ratio = (TARGET_STEM / CURRENT_STEM) ** (1.0 / STEPS)

print("stem %g -> %g in %d steps, growth %+.1f%% per step" % (
    CURRENT_STEM, TARGET_STEM, STEPS, (ratio - 1) * 100))
for i in range(1, STEPS + 1):
    stem = CURRENT_STEM * ratio ** i
    amount = (stem - CURRENT_STEM) / 2.0
    print("step %d: stem %5.1f   ProportionalWeight; amount:%d; vertical:%d; counters:%d; width:%d" % (
        i, stem, round(amount), VERTICAL, COUNTERS, WIDTH))
