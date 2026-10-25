# Rigormortise for Glyphs — 0.1 prototype

**Experimental, opt-in version.** Final native Undo/Redo checks, including fractional sidebearings, and OTF export passed. The revised adapter passed native Glyphs 3.4.1 UI Undo/Redo checks for manual sidebearings and contour edits, exact snapshot comparisons, override persistence, and OTF export on a Saddleshoe copy. The original font remains off. See `validation.json` for the recorded checks. This is not yet a promise that every Glyphs workflow or font is supported.

A local, always-on spacing adapter for Glyphs 3.4.1. Open **Edit → Rigormortise…**, then enable it for the current master. Its settings and ownership records live in the `.glyphs` document. Each master is off until explicitly enabled. Settings and ownership are independent per master.

## Controls

- Target space controls the overall rhythm. Sidebearings and affected pairs follow outline changes after a short idle period.
- Enabling Auto remembers the current spacing and kerning for that master. Initial sidebearings become adjustments relative to the automatic result, so later outline changes can still adapt.
- A manual sidebearing change becomes an adjustment relative to the automatic result.
- Pin selected spacing retains exact left/right bearings. Return selected to Auto clears those sidebearing overrides.
- Manually entered or deleted kerning is retained as an override; existing glyph, mixed, and class kerning is respected.
- Turning Auto off freezes the current ordinary Glyphs metrics/kerning. It does not remove the generated result.
- Automatic changes create a separate **Rigormortise** Undo step. Press Undo once for the automatic adjustment and again for the underlying edit. Redo reverses those steps. After Undo, Auto waits for the next edit instead of immediately reapplying the change.
- Undo patches are limited to changed metrics, pairs, and ownership fields. They skip fields edited later, preventing an older glyph's undo history from overwriting unrelated work.

The current result is written as normal Glyphs spacing and kerning and exported by Glyphs. Wait until the status returns to Auto on before saving/exporting immediately after an edit; this prototype does not intercept an export started during a pending calculation.

## Scope

Single- and multi-master Latin fonts, numbers, and punctuation. Only the enabled, selected master is monitored for edits; pending results remain bound to their originating master. Switching masters changes the panel and does not enable the other master. Non-Latin letters, combining marks, spaces, empty/open outlines, and non-exporting glyphs are excluded. Composite glyphs, hinted glyphs, and metrics-linked sides retain their metrics. Components are decomposed only for measurement, never in the font. Component and accented inheritance beyond existing Glyphs metric links is not a complete port of Graver's document model.

Existing kerning groups are honored. Generated kerning is individual pairs, not inferred classes; a dense pair table can result. Intentional overlaps can be authored as pair overrides or by disabling collision protection.

Automatic translations use the unrounded native node API and preserve node types, smoothness, handles, and vertical coordinates. The user's grid settings are not changed. No outlines are redrawn or simplified. A manual use of Glyphs' own sidebearing field may still apply Glyphs' native rounding.

## Engine

`build_engine.py` compiles the checked-in `engine/*.swift` files into the sibling `../Rigormortise.glyphsPlugin` bundle. It requires Apple's Swift command-line tools on macOS; it does not depend on a particular home directory or read the Graver checkout during normal builds. The bundled worker is currently Apple Silicon (arm64); rebuilding targets the current machine.

The vendored sources were extracted from `~/Development/proto-type/Sources/ProtoType`: full `BodySpacing.swift`, the profile/italic/metric portion of `Spacing.swift`, the bounded portion of `RenderCache.swift`, and cubic evaluation utilities from `CurveFit.swift`. `engine/Models.swift` and `engine/main.swift` adapt the input and newline-JSON protocol. `source-manifest.json` records the original full source-file SHA-256 hashes; `launcher-provenance.json` records the official Glyphs SDK loader URL and checksum. Updating these source slices is an explicit maintenance step, separate from building.

The worker is a persistent local Swift process. It caches outline profiles, computes affected pairs, and never accesses live Glyphs objects. The Python adapter reads and writes Glyphs on the main thread, debounces updates, checks document/outline/state freshness before applying, and does not run during mouse drags. No network or external services are used by the running plug-in.

## Build and tests

```
python3 build_engine.py
python3 test_master_state.py
python3 test_state.py
python3 test_baseline.py
python3 test_similar_pairs.py
python3 test_undo_state.py
python3 test_metrics.py
python3 test_engine.py
```

Run the commands above from this directory. `test_state.py`, `test_undo_state.py`, and `test_metrics.py` run without Glyphs; `test_engine.py` exercises the bundled worker using the included `engine-request.json` and `live-snapshot.json` Saddleshoe fixtures. Generated `calibrated-request.json` and `engine-result.json` are ignored by Git. Native UI Undo/Redo and export results from the original validation are retained in `validation.json`; historical one-off UI automation scripts and font exports remain in the original chat workspace and are not part of this package.

The plug-in launcher comes from Glyphs' official SDK, `Glyphs3` branch:
https://github.com/schriftgestalt/GlyphsSDK/tree/Glyphs3/Python%20Templates/General%20Plugin

Install the bundle, then restart Glyphs when convenient. Do not enable this on a production font without retaining a backup.

Installation path: `~/Library/Application Support/Glyphs 3/Plugins/Rigormortise.glyphsPlugin`.

## Repository and development installation

Runtime bundle: `Plugins/Rigormortise.glyphsPlugin`.
Engine sources, build, tests, and fixtures: `Plugins/Rigormortise/` (this directory).

The installed plugin at `~/Library/Application Support/Glyphs 3/Plugins/Rigormortise.glyphsPlugin` is symlinked to the repository bundle, like the other plugins in this repo. Restart Glyphs after Python or engine changes; an already-running controller/worker can still use the previous code. No restart is required merely to relocate identical files.

Migrated from the Codex workspace `2026-10-20/yo-x20/work/graver-spacing` on 2026-10-24. The runtime bundle was byte-for-byte identical to the installed working version at migration.

## Direct master spacing (2026-10-24)

Open **Edit → Rigormortise…** in your existing document. Select a master,
choose the matching Saddleshoe calibration, and enable **Automatic spacing on
this master**. The normal workflow edits that document directly; it creates no
new files. Use **Use Contour spacing** to switch the reviewed algorithm on/off.
Each master retains its own calibration, target space, enable state, manual
sidebearing adjustments, and kerning ownership when the font is saved.

Enabling Auto preserves existing authored kerning. To replace a previous
kerning result, click **Replace existing kerning on this master**. This enables
Auto and recalculates kerning on that master, preserving explicit Rigormortise pins.
It replaces existing glyph, mixed, and class pairs, including unclassified
pairs from another tool; it cannot infer which of those were hand tuned. The replacement is undoable; keep Auto in preserve mode if those existing
pairs must stay unchanged. Turn
off other live kerning tools on the same document before using Rigormortise.

Native validation on a disposable two-master Saddleshoe copy covers master
isolation, full replacement, manual overrides, undo/redo after switching
masters, stale-worker rejection, fractional curves, and save/reload. See
`direct-master-validation.json`. Original single-master settings migrate only
to the first master; they are never copied onto the second master.

## Optional Contour preview

Open **Edit → Rigormortise…**, choose the Saddleshoe calibration, and click
**Create Stock + Contour preview**. This copies the selected master into two new,
independent, single-master documents. The source can have multiple masters; its
outlines, spacing, kerning and auto-spacing settings are not modified. Use **View
Stock**, **View Contour**, and **Back to source** to compare. Save either preview
with Save As if you want to keep working on it.

The Regular preset is the reviewed v3 candidate. The Wide Black preset is the v3
study counterpart. Calibration is bundled: no manual pair survey, NumPy install,
or external spacing runtime is needed. These are Saddleshoe calibrations, not universal
models for unrelated fonts or different units-per-em. No glyph-name or pair-name
exceptions participate in prediction. Facing contours are measured anew after
edits. The compiled engine normally takes about 70–90 ms for 81 glyphs on the
validation Mac, plus the UI's existing idle delay and native application time.

Preview copies replace unpinned reference kerning. Explicit Rigormortise sidebearing
adjustments/pins, Rigormortise pair pins, and metrics-key/component locks survive.
Unclassified kerning in a source from another tool remains intact in the source;
it is not treated as manually pinned in the comparison. Extension user data is
removed **only from the new copies** to prevent competing automation. Rigormortise
overrides are explicitly restored afterward. Originals retain all metadata.
The copies retain every glyph, but marks, separators and unsupported outlines
remain outside automatic spacing, as before.

In any document, **Use Contour spacing** switches between stock and contour
calculation at the same target space. Later manual sidebearing edits and kerning
changes retain ownership across switches. **Automatic spacing** off freezes the
current result. The existing conditional native Undo/Redo path handles generated
changes. Mode and calibration choice survive saving/reopening a preview. The
three navigation buttons refer to the comparison created in the current session;
after restart, open the saved comparison/source documents normally.

The contour model adds a learned residual to stock Graver, then reapplies the
existing sampled clearance and punctuation guards. It preserves the approved
word rhythm. Some quote/punctuation combinations remain too loose. Two additional
punctuation experiments failed to improve overall agreement and are not enabled.
The preview does not promise collision-proof arbitrary outlines or unattended
production export, and does not make masters interpolation-compatible.

Run `python3 test_contour.py` after building for frozen-output, exact stock
fallback, renamed glyphs, incremental updates, manual-bearing precedence,
tracking, live geometry and invalid-preset coverage. Native preview validation
is recorded in `preview-validation.json`. The runtime ships inference coefficients, contour descriptors and a small
regression fixture. Research notes and source material are not distributed.

## Name and saved-settings compatibility

Rigormortise was previously named Graver Spacing. The document metadata keys
remain unchanged so existing enable states, calibrations, manual adjustments
and kerning ownership continue to load without conversion. Remove the old
plugin bundle when installing the renamed bundle to avoid duplicate menus.


## Remembering your starting spacing (2026-10-25)

The first activation saves an immutable baseline for each master in the font's
metadata: eligible glyph sidebearings/widths and the complete master kerning table.
It keeps the exact initial metrics, including fractional widths. Authored glyph,
mixed, class and zero kerning remain protected. Automatic kerning can fill pairs
that have no authored value.

Initial sidebearings are retained as offsets from the calculated result. Outline
edits can therefore adjust spacing without discarding your starting decisions.
**Return selected to Auto** clears those offsets for selected glyphs; **Pin
selected spacing** holds exact bearings instead. New eligible glyphs added while
Auto is running receive automatic spacing.

The last applied state also persists in the document. Manual spacing and kerning
changes made with Auto off are recognized on re-enabling, including pair deletions.
Re-enabling retains the current metrics; it does not replace the original baseline.
Save the font to retain this memory across closing/reopening.

**Restore starting spacing + kerning** restores the saved bearings and kerning,
clears current Rigormortise overrides, and turns Auto off. It is undoable. Outlines
are not restored: current shapes and metrics links remain authoritative, deleted
glyphs are skipped, and exact starting widths are restored when shapes are unchanged.
The saved baseline remains available after restoration.

Existing installations capture their current values on the next activation/update;
values overwritten before this feature cannot be recovered automatically. The
optional Stock/Contour comparison still deliberately calculates new spacing in its
copies. Native capture, off/on, save/reopen, restore and Undo/Redo checks are recorded
in `baseline-validation.json`.


## Apply to similar pairs

With Auto enabled, adjust a pair's kerning in Glyphs. Open **Apply to similar
pairs…** in the Rigormortise panel. Enter its two glyph names (for example,
`n n`) and click **Use recorded edit**. Repeated nudges retain the total change
from the first observed value; a new exception measures against inherited class
kerning. You can also enter the intended change in units: positive loosens,
negative tightens. The example pair itself remains your manual override.

Choose **Similarity** and **Strength**, then **Preview matches**. The list shows
all affected pairs, their match score, current kerning, and proposed kerning.
**Open before / after proof** creates a disposable font copy showing the first
16 matches: before on the left, after on the right, in list order. The source
is unchanged until **Apply rule**. Preview again after changing the font or any
settings. The panel remains bound to the source master, including while viewing
the proof; changing the source's selected master requires reopening the panel.

Similarity compares sampled facing silhouettes at shared vertical positions,
normalized by x-height. Letter names do not determine similarity. A high threshold
is intentionally conservative; an unusual pair may have no close matches.
Closer matches receive more of the adjustment. The closest applicable rule wins
when examples overlap, so their effects do not accumulate. Match percentages
are geometric scores, not probabilities or a promise of optical equivalence.

Rules are saved per master in the font metadata and recompute against current
outlines during automatic updates. Their reference shape is the approved example
at creation time. Existing authored glyph/mixed/class pairs and manual pins are
excluded. Collision and punctuation guards still apply to learned tightening.
Ordinary spacing and model output are unchanged when there are no rules.

Select any saved rule and **Remove rule** to recalculate without it; manual
pair overrides remain protected. Applying/removing rules supports native Undo/Redo.
Save the font to retain rules across reopening. **Restore starting spacing +
kerning** also clears learned rules. This first version learns only from explicitly
approved examples; it does not infer a broad preference from every edit.

`test_similar_pairs.py` covers geometry matching, renamed glyphs, strength,
non-stacking, inherited/class/manual ownership, cumulative edits, persistence,
independent rule undo, live geometry and engine collision protection. Native
preview/application/proof, stale-preview rejection, Undo/Redo, save/reload and
removal checks are recorded in `similar-pairs-validation.json`.
