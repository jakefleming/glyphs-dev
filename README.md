# glyphs-dev

Scripts and plugins for Glyphs 3.

## Scripts

Symlinked into `~/Library/Application Support/Glyphs 3/Scripts/`. Reload in Glyphs with Cmd+Opt+Shift+Y. Assign hotkeys in Glyphs > Settings > Shortcuts.

- **Flatten Curves** — removes handles and replaces each curve with `STEPS` straight segments.
- **Cornerize Curves** — replaces each curve with a single corner point at the intersection of the two extended handles.
- **Cornerize Curves (Threshold)** — same, but only when the corner lands within `MAX_DEV` units of the curve; big sweeping curves get flattened instead. This is the good one.
- **Remove Shallow Points** — deletes points that deviate less than `TOL` units from the straight line between their neighbors. Run after cornerizing to clean up.

Typical combo: Cornerize Curves (Threshold), then Remove Shallow Points.

- **Lucas Weight Steps** — prints geometrically spaced stem widths from `CURRENT_STEM` to `TARGET_STEM` (Lucas de Groot's interpolation theory: constant growth *percentage* per step, so the weight progression looks optically even), along with the matching `ProportionalWeight` custom parameter for each instance. Run once toward Black and once toward Thin.

## Plugins

Symlinked into `~/Library/Application Support/Glyphs 3/Plugins/`. Plugins load at app startup, so restart Glyphs after changes.

- **Proportional Weight** (`ProportionalWeight.glyphsFilter`) — Filter > Proportional Weight. Adds or removes weight by offsetting the outline, then rescales back to the original bounding box so proportions and width are preserved. Sliders:
  - **Weight** — offset amount in units; positive = bolder.
  - **Vertical %** — how much of the weight goes to horizontals relative to verticals (anisotropy). 100 = round nib.
  - **Counters %** — how much of the offset applies to counter contours. Below 100 protects counters when bolding (weight goes to the outside of the letter instead of clogging the counters, RMX-style); 100 = plain offset. A counter that still collapses (offset exceeds its size) is dropped cleanly instead of turning inside out.
  - **Width %** — condenses/extends outlines and advance width together.
  - **Harmony %** — slides smooth nodes along their handle line to the curvature-continuous (G2) position; kills the subtle kink at curve joins. 0 = off, 100 = fully harmonized. Prior art: RMX Harmonizer, Hobby splines.
  - **Balance %** — equalizes each curve segment's two handle fractions (measured against the tangent intersection) without changing endpoints or tangent directions. Prior art: Curve Equalizer.

  Harmony and Balance run before the weight offset, so weight is applied to the cleaned outline. Both are no-ops on straight-line fonts.

  Also usable as a custom parameter: `ProportionalWeight; amount:N; vertical:N; counters:N; width:N; harmony:N; balance:N`.

### Python plugin bundle anatomy

A hand-built Python plugin needs, or it won't load:

1. `Contents/MacOS/plugin` — the generic loader binary (copied from any working Python plugin).
2. `Info.plist` keys: `CFBundleExecutable = plugin`, `PyMainFileNames = [plugin.py]`, `NSPrincipalClass = <class name in plugin.py>`.
3. A valid signature after touching the binary: `codesign --force --deep --sign - <bundle>`.
