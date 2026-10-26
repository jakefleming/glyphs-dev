# Even Out (Preview)

Even Out looks for recurring stroke widths in the current master, then uses
those ranges to ease bulges and pinches in curves. You don't need to pick
reference glyphs.

Select glyphs and open **Filter → Even Out (Preview)**. The dialog reports how
many weight ranges it found. Move **Amount** to preview the correction;
**0%** shows the original. Click **Apply** to keep it or **Cancel** to restore
the original. Deselect points first: this version works on whole glyphs.

The reference stays fixed while the dialog is open. Reopen it after changing
the font to learn a new reference. Only the current master is considered.

## What it measures

The tool samples opposite edges across the ink and groups their widths by
stroke direction and whether the edge is straight or curved. Scripts,
capitals, lowercase and other glyph categories are kept separate where the
font supplies that information. Each range needs agreement from at least four
distinct outlines. Identical alternates count once. Large fonts are sampled,
with up to 240 eligible glyphs considered.

A range allows some variation. It is not a command to make every stroke the
same thickness. Several supported ranges can coexist, and measurements far
outside them are left alone.

## What it changes

This first version adjusts cubic handles and smooth joins between curves.
Nodes touching straight segments and corner nodes stay fixed. Handle
directions, node types and node counts are retained. Widths are measured again
after fitting, and changes that fail to improve them are discarded. Sampled
contour intersections are also checked.

Straight stems provide context but are not corrected yet. Components, hints,
open paths, quadratic paths and complex outlines are skipped. Node count is
preserved, but that alone does not guarantee good interpolation between
masters. Inspect intermediate weights if you use the correction in a family.

This is an experimental filter. It cannot determine whether an unusual weight
is intentional, and its measurements are an approximation. Check the preview
in words as well as enlarged outlines. It does not run during export.

## Development

The engine is plain Python and has no third-party dependencies. From the
repository root:

```sh
python3 -m unittest discover -s Plugins/EvenOut -p 'test_*.py' -v
```

Native checks use a disposable synthetic font. The dialog's Cancel, Apply,
Undo and Redo should be checked after changes to the Glyphs integration.
