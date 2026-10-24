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

`build_engine.py` compiles exact source slices from the current local Graver checkout:

- `BodySpacing.swift` in full
- `OpticalSpacing.Profile`, italic measurement, and metric data structures from `Spacing.swift`
- the bounded `RenderCache` and cubic evaluation utilities

`engine/Models.swift` adapts outline/metric inputs; `engine/main.swift` is a newline-JSON worker. `source-manifest.json` records the SHA-256 hashes used. This shares source calculations at build time. Graver's app has not been refactored to depend on a new package or modified by this task.

The worker is a persistent local Swift process. It caches outline profiles, computes affected pairs, and never accesses live Glyphs objects. The Python adapter reads and writes Glyphs on the main thread, debounces updates, checks document/outline/state freshness before applying, and does not run during mouse drags. No network or external services are used by the running plug-in.

## Build and tests

```
python3 build_engine.py
python3 test_state.py
python3 test_undo_state.py
python3 test_metrics.py
python3 test_engine.py
```

The engine test uses the captured Saddleshoe fixture. Native integration scripts run through Glyphs' Macro Panel and target `Saddleshoe-Graver-Spacing-Test.glyphs` exclusively. `native_tests.py` is disabled: its old timer-based mutation harness incorrectly manipulated Glyphs event groups. `ui-*.json` and `validation.json` record the replacement tests driven through the normal editor UI; Macro scripts capture read-only snapshots. `verify_font.py` compares the saved test font to the pre-spacing snapshot, checking all node geometry up to a uniform horizontal translation and preserving all existing kerning entries.

The plug-in launcher comes from Glyphs' official SDK, `Glyphs3` branch:
https://github.com/schriftgestalt/GlyphsSDK/tree/Glyphs3/Python%20Templates/General%20Plugin

Install the bundle, then restart Glyphs when convenient. Do not enable this on a production font without retaining a backup.

Installation path: `~/Library/Application Support/Glyphs 3/Plugins/GraverSpacing.glyphsPlugin`.
