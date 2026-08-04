# glyphs-dev

Scripts and plugins for Glyphs 3.

## Scripts

Symlinked into `~/Library/Application Support/Glyphs 3/Scripts/`. Reload in Glyphs with Cmd+Opt+Shift+Y. Assign hotkeys in Glyphs > Settings > Shortcuts.

- **Flatten Curves** — removes handles and replaces each curve with `STEPS` straight segments.
- **Cornerize Curves** — replaces each curve with a single corner point at the intersection of the two extended handles.
- **Cornerize Curves (Threshold)** — same, but only when the corner lands within `MAX_DEV` units of the curve; big sweeping curves get flattened instead. This is the good one.
- **Remove Shallow Points** — deletes points that deviate less than `TOL` units from the straight line between their neighbors. Run after cornerizing to clean up.

Typical combo: Cornerize Curves (Threshold), then Remove Shallow Points.

## Plugins

Symlinked into `~/Library/Application Support/Glyphs 3/Plugins/`. Plugins load at app startup, so restart Glyphs after changes.

- **Proportional Weight** (`ProportionalWeight.glyphsFilter`) — Filter > Proportional Weight. Slider adds or removes weight by offsetting the outline, then rescales back to the original bounding box so proportions and width are preserved. Also usable as a custom parameter: `Proportional Weight; amount:N`.

### Python plugin bundle anatomy

A hand-built Python plugin needs, or it won't load:

1. `Contents/MacOS/plugin` — the generic loader binary (copied from any working Python plugin).
2. `Info.plist` keys: `CFBundleExecutable = plugin`, `PyMainFileNames = [plugin.py]`, `NSPrincipalClass = <class name in plugin.py>`.
3. A valid signature after touching the binary: `codesign --force --deep --sign - <bundle>`.
