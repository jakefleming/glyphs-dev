# Rigormortise for Glyphs

Rigormortise updates spacing and kerning as you draw. Change an outline, pause,
and it recalculates the affected spacing. You can correct the result, pin a
sidebearing, or use a pair you've adjusted as an example for similar pairs.

It works in your open Glyphs document. The result is ordinary sidebearings and
kerning, so you can turn the plugin off and carry on editing or export the font.
Settings are saved in the `.glyphs` file, separately for each master.

This is version 0.1, tested in Glyphs 3.4.1. Try it on a copy first. The bundled
Contour presets were developed for Saddleshoe; their results on other fonts,
particularly italic punctuation, still need work.

## Installation

Install [`Rigormortise.glyphsPlugin`](../Rigormortise.glyphsPlugin) in:

```
~/Library/Application Support/Glyphs 3/Plugins/
```

Restart Glyphs, then open **Edit → Rigormortise…**. The bundled engine runs on
Apple Silicon. To build it for another Mac, see [Development](#development).

If you have the old **Graver Spacing** bundle installed, remove it to avoid
getting two menus. Rigormortise still reads its saved settings.

## Start with your existing spacing

Select a master and enable **Automatic spacing on this master**. Each master
starts with Auto off. Enabling one does not enable the others.

On first activation, Rigormortise remembers that master's spacing and complete
kerning table. Your current sidebearings become offsets from its calculated
values. This lets the spacing follow later outline changes while retaining your
adjustments. Existing kerning, including class pairs and explicit zero values,
is preserved. Auto fills pairs which have no authored value.

**Target space** controls the overall spacing. **Use Contour spacing** adds a
contour-based correction to the stock calculation, using the selected preset.
The Regular and Wide Black presets are calibrated for Saddleshoe. They aren't
general-purpose presets for every typeface or units-per-em value.

Only the selected master is monitored. If you switch masters during a
calculation, its result still belongs to the master that started it. The panel
shows the settings for your new selection.

Turn off any other live spacing tool working on the same document.

## Make corrections

A manual sidebearing edit becomes an offset from the automatic result. For an
exact value that must stay put, use **Pin selected spacing**. **Return selected
to Auto** clears these sidebearing adjustments and pins for the selected glyphs.

Manual kerning edits and deletions are remembered too. This includes changes
made while Auto is off: Rigormortise picks them up when you enable it again.
Save the font to keep these records across sessions.

If you want to replace the existing kerning, use **Replace existing kerning on
this master**. It enables Auto and recalculates that master's pairs. It keeps
explicit Rigormortise pins, but replaces other glyph, mixed and class kerning.
There is no reliable way to tell whether an existing pair was set by hand or by
another tool, so this command replaces both. It can be undone.

Turning Auto off leaves the current spacing in place. It does not restore the
spacing you started with.

## Apply an adjustment to similar pairs

Suppose you tighten a pair and want to try the same adjustment elsewhere:

1. With Auto on, adjust the pair in Glyphs.
2. Open **Apply to similar pairs…** and enter the two glyph names, such as `n n`.
3. Click **Use recorded edit**. Alternatively, enter a change in units yourself:
   positive opens the space, negative closes it.
4. Click **Preview matches**. The list shows each proposed pair, its similarity
   score, and its current and proposed kerning.
5. Put any exceptions in **Skip pairs**, for example `i period, j period`, then
   preview again.
6. Check the result and click **Apply rule**.

**Similarity** defaults to 90%. Raise it to require a closer match.
**Strength** controls how much of your adjustment to transfer. Closer matches
receive more of the adjustment. The score measures contour similarity; 90%
doesn't mean a 90% chance that the spacing looks right.

**Open before / after proof** makes a temporary font showing the first 16
matches, in list order. Before is on the left; after is on the right. You can
inspect this without changing the source. The panel stays attached to the source
master while you view the proof. Reopen it to work on a different master.

Matching uses the facing outlines, not glyph names. It compares the vertical
region where both glyphs have ink, relative to the x-height, and compensates for
italic slant. Small differences in terminal position are allowed. Large
overhangs or different arrangements of detached marks make a match less likely.
Some examples won't produce any useful matches.

The example pair stays a manual override. Repeated nudges are recorded as a
total change from the first observed value; an exception to class kerning is
measured from the inherited value.

Applying a rule saves the example's shape and the list of pairs you reviewed.
The adjustment is recalculated as their outlines change, but new pairs cannot
join that list without another preview. Manual kerning, pins and pairs approved
by earlier rules are excluded. Where rules overlap, the closest match wins;
adjustments aren't added together. Collision and punctuation checks still apply
to tightening.

Change the font or the settings after previewing, and you'll need to preview
again before applying. **Remove rule** recalculates the spacing without that
rule and makes its pairs available to later rules. Manual overrides remain.
Both applying and removing rules support Undo/Redo. Older saved rules retain
their original matching behaviour.

## Undo and restore

Automatic changes get their own **Rigormortise** Undo step. Undo once to reverse
the spacing calculation, then again to reverse the outline or metric edit that
caused it. Auto waits for another edit before recalculating, so it doesn't
immediately undo your Undo.

**Restore starting spacing + kerning** returns to the values saved on first
activation, clears Rigormortise overrides and similar-pair rules, and turns Auto
off. This is also undoable. The saved starting values remain available.

Restoring spacing doesn't restore outlines. Current metrics links are respected,
deleted glyphs are skipped, and exact starting widths can be restored when the
shapes are unchanged. Re-enabling Auto doesn't overwrite the original saved
values. New eligible glyphs receive automatic spacing.

For documents used before the starting-spacing feature existed, the plugin
records the values it finds on the next activation or update. It cannot recover
values which were already overwritten.

## Compare Stock and Contour

**Create Stock + Contour preview** makes two single-master copies for comparison.
The source document is left alone. Use **View Stock**, **View Contour** and
**Back to source** to move between them. Save a preview with Save As if you want
to keep it. After restarting Glyphs, open the saved files normally; the navigation
buttons refer only to the comparison made in the current session.

These copies calculate fresh spacing. Existing kerning is replaced except for
Rigormortise pair pins. Rigormortise sidebearing adjustments and pins, metrics
links, and component locks are retained. Other extension metadata is removed
from the copies to keep other automation from running there.

All glyphs are copied, including those the spacer doesn't handle. The Contour
calculation adds a learned correction to stock spacing and then checks clearance
and punctuation. Some punctuation combinations are still too loose. Comparing
the modes is useful; neither mode removes the need to look at the result.

## Current limits

The plugin handles Latin letters, numbers and punctuation in single- or
multi-master fonts. It skips non-Latin letters, combining marks, spaces,
non-exporting glyphs, and empty or open outlines. Component and hinted glyphs
keep their metrics, as do sides controlled by metrics keys. Components are
decomposed for measurement only. Accented-glyph spacing relies on existing
Glyphs metrics links; there is no additional inheritance system yet.

Existing kerning groups are respected, but generated kerning is stored as
individual pairs. A large font can therefore acquire a large kerning table.
Intentional overlaps can be set as manual pair overrides, or you can turn off
**Prevent collisions**. That check samples outlines; it is not a guarantee
against every possible collision.

Spacing changes translate outlines without rounding their node coordinates.
Node types, handles, smoothness and vertical coordinates stay intact. Your grid
settings aren't changed. Editing a sidebearing through Glyphs' own field may
still invoke Glyphs' rounding. Rigormortise doesn't redraw paths or make masters
compatible for interpolation.

Before saving or exporting immediately after an edit, wait for the status to
return to Auto on. The plugin doesn't delay an export while a calculation is
pending.

## Development

The runtime bundle is in `Plugins/Rigormortise.glyphsPlugin`. This directory
contains the Swift sources, build script, tests and fixtures. A development
installation can symlink the bundle into Glyphs' Plugins directory. Restart
Glyphs after changing the Python code or rebuilding the engine.

The Python adapter reads and writes Glyphs objects on the main thread. A local
Swift worker measures outlines and calculates spacing. It stays running and
caches profiles between requests. The adapter waits for a pause in editing,
avoids mouse drags, and discards results if the document has changed underneath
them. The plugin makes no network requests.

The engine sources come from Graver: `BodySpacing.swift`, the spacing and profile
code in `Spacing.swift`, parts of `RenderCache.swift`, and cubic utilities from
`CurveFit.swift`. `Models.swift` and `main.swift` provide the worker's data types
and newline-delimited JSON protocol. `source-manifest.json` records the source
hashes. Building uses the files in this repository; it doesn't read a separate
Graver checkout. Updating those source files is a separate maintenance task.

The launcher comes from the [Glyphs SDK](https://github.com/schriftgestalt/GlyphsSDK/tree/Glyphs3/Python%20Templates/General%20Plugin).
Its checksum is recorded in `launcher-provenance.json`.

Run these commands from this directory. Building requires Apple's Swift
command-line tools and targets the current machine.

```sh
python3 build_engine.py
python3 test_master_state.py
python3 test_state.py
python3 test_baseline.py
python3 test_similar_pairs.py
python3 test_similar_review.py
python3 test_undo_state.py
python3 test_metrics.py
python3 test_engine.py
python3 test_contour.py
```

The tests run outside Glyphs. Engine tests use the bundled worker and included
fixtures. Generated request and result files are ignored by Git. The runtime
includes model coefficients, contour descriptors and a regression fixture;
private research material is not included.

Native checks in Glyphs cover Undo/Redo, fractional sidebearings, outline edits,
export, master switching, saved settings, restoration and similar-pair proofs.
The results are in `validation.json`, `direct-master-validation.json`,
`preview-validation.json`, `baseline-validation.json`,
`similar-pairs-validation.json` and `similar-review-validation.json`.

Saved metadata still uses the old Graver Spacing keys so existing documents load
without conversion. Settings from the original single-master version migrate to
the first master only.
