# Graver Spacing for Glyphs — 0.1 prototype

**Experimental, opt-in version.** Final native Undo/Redo checks, including fractional sidebearings, and OTF export passed. The revised adapter passed native Glyphs 3.4.1 UI Undo/Redo checks for manual sidebearings and contour edits, exact snapshot comparisons, override persistence, and OTF export on a Saddleshoe copy. The original font remains off. See `validation.json` for the recorded checks. This is not yet a promise that every Glyphs workflow or font is supported.

A local, always-on spacing adapter for Glyphs 3.4.1. Open **Edit → Graver Spacing…**, then enable it for the current font. Its settings and ownership records live in the `.glyphs` document. It is off for documents that have not explicitly enabled it.

## Controls

- Target space controls the overall rhythm. Sidebearings and affected pairs follow outline changes after a short idle period.
- A manual sidebearing change becomes an adjustment relative to the automatic result.
- Pin selected spacing retains exact left/right bearings. Return selected to Auto clears those sidebearing overrides.
- Manually entered or deleted kerning is retained as an override; existing glyph, mixed, and class kerning is respected.
- Turning Auto off freezes the current ordinary Glyphs metrics/kerning. It does not remove the generated result.
- Automatic changes create a separate **Graver Spacing** Undo step. Press Undo once for the automatic adjustment and again for the underlying edit. Redo reverses those steps. After Undo, Auto waits for the next edit instead of immediately reapplying the change.
- Undo patches are limited to changed metrics, pairs, and ownership fields. They skip fields edited later, preventing an older glyph's undo history from overwriting unrelated work.

The current result is written as normal Glyphs spacing and kerning and exported by Glyphs. Wait until the status returns to Auto on before saving/exporting immediately after an edit; this prototype does not intercept an export started during a pending calculation.

## Scope

First version: single-master Latin fonts, numbers, and punctuation. Multi-master fonts are rejected without changes. Non-Latin letters, combining marks, spaces, empty/open outlines, and non-exporting glyphs are excluded. Composite glyphs, hinted glyphs, and metrics-linked sides retain their metrics. Components are decomposed only for measurement, never in the font. Component and accented inheritance beyond existing Glyphs metric links is not a complete port of Graver's document model.

Existing kerning groups are honored. Generated kerning is individual pairs, not inferred classes; a dense pair table can result. Intentional overlaps can be authored as pair overrides or by disabling collision protection.

Automatic translations use the unrounded native node API and preserve node types, smoothness, handles, and vertical coordinates. The user's grid settings are not changed. No outlines are redrawn or simplified. A manual use of Glyphs' own sidebearing field may still apply Glyphs' native rounding.

## Engine

`build_engine.py` compiles the checked-in `engine/*.swift` files into the sibling `../GraverSpacing.glyphsPlugin` bundle. It requires Apple's Swift command-line tools on macOS; it does not depend on a particular home directory or read the Graver checkout during normal builds. The bundled worker is currently Apple Silicon (arm64); rebuilding targets the current machine.

The vendored sources were extracted from `~/Development/proto-type/Sources/ProtoType`: full `BodySpacing.swift`, the profile/italic/metric portion of `Spacing.swift`, the bounded portion of `RenderCache.swift`, and cubic evaluation utilities from `CurveFit.swift`. `engine/Models.swift` and `engine/main.swift` adapt the input and newline-JSON protocol. `source-manifest.json` records the original full source-file SHA-256 hashes; `launcher-provenance.json` records the official Glyphs SDK loader URL and checksum. Updating these source slices is an explicit maintenance step, separate from building.

The worker is a persistent local Swift process. It caches outline profiles, computes affected pairs, and never accesses live Glyphs objects. The Python adapter reads and writes Glyphs on the main thread, debounces updates, checks document/outline/state freshness before applying, and does not run during mouse drags. No network or external services are used by the running plug-in.

## Build and tests

```
python3 build_engine.py
python3 test_state.py
python3 test_undo_state.py
python3 test_metrics.py
python3 test_engine.py
```

Run the commands above from this directory. `test_state.py`, `test_undo_state.py`, and `test_metrics.py` run without Glyphs; `test_engine.py` exercises the bundled worker using the included `engine-request.json` and `live-snapshot.json` Saddleshoe fixtures. Generated `calibrated-request.json` and `engine-result.json` are ignored by Git. Native UI Undo/Redo and export results from the original validation are retained in `validation.json`; historical one-off UI automation scripts and font exports remain in the original chat workspace and are not part of this package.

The plug-in launcher comes from Glyphs' official SDK, `Glyphs3` branch:
https://github.com/schriftgestalt/GlyphsSDK/tree/Glyphs3/Python%20Templates/General%20Plugin

Install the bundle, then restart Glyphs when convenient. Do not enable this on a production font without retaining a backup.

Installation path: `~/Library/Application Support/Glyphs 3/Plugins/GraverSpacing.glyphsPlugin`.

## Repository and development installation

Runtime bundle: `Plugins/GraverSpacing.glyphsPlugin`.
Engine sources, build, tests, and fixtures: `Plugins/GraverSpacing/` (this directory).

The installed plugin at `~/Library/Application Support/Glyphs 3/Plugins/GraverSpacing.glyphsPlugin` is symlinked to the repository bundle, like the other plugins in this repo. Restart Glyphs after Python or engine changes; an already-running controller/worker can still use the previous code. No restart is required merely to relocate identical files.

Migrated from the Codex workspace `2026-10-20/yo-x20/work/graver-spacing` on 2026-10-24. The runtime bundle was byte-for-byte identical to the installed working version at migration.
