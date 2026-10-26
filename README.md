# glyphs-dev

Plugins and scripts for drawing, transforming and spacing type in Glyphs 3.

## Installation

Put plugin bundles in:

```
~/Library/Application Support/Glyphs 3/Plugins/
```

Put scripts in:

```
~/Library/Application Support/Glyphs 3/Scripts/
```

You can symlink these files from the repository while developing. Restart Glyphs
for plugin changes. Reload scripts with **Cmd+Opt+Shift+Y**. Script shortcuts can
be assigned in **Glyphs → Settings → Shortcuts**.

## Plugins

### Bastard

[Bastard](Plugins/Bastard.glyphsFilter) changes stroke weight. Open
**Filter → Bastard** and set **Weight**: positive makes strokes heavier,
negative makes them lighter.

**Counters** controls how much weight moves outward instead of into the white
space. **Rounds** controls how closely curves retain their original tension.
**Vertical** sets the amount applied to horizontal strokes relative to vertical
ones. Check tight joins and small counters when making large changes.

### Curse

[Curse](Plugins/Curse.glyphsFilter) makes an optically corrected oblique. Open
**Filter → Curse**, set the angle, and adjust the corrections for curves,
diagonals, stems and terminals. **Keep nodes on extremes** adjusts vertical
extrema after slanting.

It transforms the existing outlines. It won't draw a new italic `a` or `g` for
you. Curves and joins still need inspection after applying it.

### lil Devil

[lil Devil](Plugins/LilDevil.glyphsFilter) combines weight changes with controls
for proportions and curve shape. Open **Filter → lil Devil**. When applied to a
whole glyph, the weight offset is rescaled to its original bounds. With points
selected, the offset can be applied locally instead.

Use **Weight** and **Counters** to control the black and white space, and the
width and height controls to change proportions. Stress, pressure, slant and
counter position give you further ways to reshape the letters.

**Harmony** adjusts smooth joins to reduce changes in curvature. **Balance**
equalizes the handle proportions within each curve. These run after the other
transformations and have no effect on straight segments.

For instance filters, a basic custom parameter is:

```
ProportionalWeight; amount:20; vertical:100; counters:80; width:100; harmony:0; balance:0
```

### Even Out (Preview)

[Even Out](Plugins/EvenOut/README.md) learns recurring stroke widths from the
current master and uses them to ease bulges and pinches in curves. Open
**Filter → Even Out (Preview)** and adjust **Amount**. No reference glyphs need
to be chosen. This first version keeps straight stems fixed and skips uncertain
geometry; inspect the preview before applying it.

### Rigormortise

[Rigormortise](Plugins/Rigormortise/README.md) updates spacing and kerning as you
draw. Open **Edit → Rigormortise…** and enable it for the selected master. It
remembers your starting spacing and keeps manual adjustments. You can also
preview how an adjustment to one pair would work on similar pairs.

See the [Rigormortise guide](Plugins/Rigormortise/README.md) for controls,
restoration, current limits, and build instructions.

### Push to Git

[Push to Git](Plugins/PushToGit.glyphsPlugin) adds **File → Save, Commit & Push**
(**Ctrl+Cmd+S**). It saves the current font, commits it and pushes to its Git
remote. The font must already belong to a Git repository. By default, it stages
only the font file. A notification reports the result.

## Scripts

- **Flatten Curves** replaces each curve with `STEPS` straight segments.
- **Cornerize Curves…** asks for a threshold in font units and remembers your
  last value (30 by default). It replaces a cubic curve with a corner where its
  endpoint tangents meet, provided that corner is within the threshold of the
  curve's midpoint. Higher values allow more pronounced corners. Curves that
  exceed the threshold, or have no suitable intersection, become three straight
  segments. It works on the selected layers; Cancel leaves the outlines alone.
- **Remove Shallow Points** removes points that deviate less than `TOL` units
  from the line between their neighbours.

For angular outlines, try **Cornerize Curves…** followed by
**Remove Shallow Points**. Set the corner threshold in the dialog; adjust
`STEPS` and `TOL` in the other scripts for the amount of detail you want to keep.

## Development

Python plugin bundles contain a loader at `Contents/MacOS/plugin` and an
`Info.plist` that names the Python entry point and principal class. The class
name must match the implementation in `Contents/Resources/plugin.py`.

After editing a signed bundle, refresh its local signature:

```sh
codesign --force --deep --sign - path/to/Plugin.glyphsFilter
```

Curse has a regression harness that runs outside Glyphs:

```sh
python3 Scripts/_makeitalic_harness.py
```

It currently reports four failures against its saved baseline. Inspect its
output as well as the process exit status.
