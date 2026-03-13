# Cross-Plugin Contract

This document defines the three handoff points between the **distill** and
**buffer** plugins. Any change to these interfaces requires updating both
plugins and this document.

---

## Handoff 1: Alpha Entry Creation

**Direction**: distill `integrate` → buffer alpha bin

**Mechanism**: `buffer_manager.py alpha-write` called via stdin JSON payload.

**Schema**: `alpha-entry.schema.json` (cross_source entries)

**Required fields**:
- `type`: `"cross_source"`
- `source_folder`: kebab-case folder name
- `key`: `"Source:ConceptName"` format
- `distillation`: filename of distillation document
- `marker`: normalized concept key matching `<!-- CONCEPT:key -->`

**Optional fields**:
- `maps_to`: project framework mapping (default `""`)
- `ref`: source citation reference
- `suggest`: null (reserved)
- `body`: null or project-specific notes (< 10 lines)
- `origin`: `"distill"` (default) or `"session"`

**Concept key format**: `Source:ConceptName` where Source is the author/short
label and ConceptName is the display name (not normalized).

**Source folder naming**: `kebab-case(source_label)` — see CONVENTIONS.md §2.

**ID assignment**: `alpha-write` auto-assigns the next available `w:N` ID.

---

## Handoff 2: Convergence Web Edge Creation

**Direction**: distill `integrate` → buffer alpha bin

**Mechanism**: Same `buffer_manager.py alpha-write` command.

**Schema**: `convergence-web.schema.json`

**Required fields**:
- `type`: `"convergence_web"`
- `source_folder`: kebab-case folder that identified the convergence
- `thesis`: `{ "ref": "w:N", "label": "Source:Concept" }`
- `athesis`: `{ "ref": "w:N", "label": "Source:Concept" }`
- `synthesis`: `"[tag] description"` — tag from CONVENTIONS.md §5
- `metathesis`: what each concept does independently (evolutory)

**Optional fields**:
- `context`: 1-2 sentences on project significance
- `origin`: `"distill"` (default) or `"session"`

**Tetradic structure**: All four fields (thesis, athesis, synthesis,
metathesis) are mandatory. The synthesis tag vocabulary is enumerated in
`convergence-web.schema.json` and CONVENTIONS.md §5.

**ID assignment**: `alpha-write` auto-assigns the next available `cw:N` ID.

---

## Handoff 3: Sigma Hook Reads Alpha Index

**Direction**: buffer sigma_hook ← alpha `index.json`

**Schema**: `alpha-index.schema.json`

**Read pattern** (sigma_hook.py):
```python
alpha_idx = read_json(os.path.join(alpha_dir, 'index.json'))
concept_index = alpha_idx.get('concept_index', {})
sources_data = alpha_idx.get('sources', {})
```

**Assumptions**:
- `concept_index` is `Dict[str, List[str]]` — concept name → entry IDs
- `sources_data` is `Dict[str, SourceSummary]` — folder name → summary object
- Both fields always exist (default to empty dict if missing)
- Entry IDs follow `w:N` or `cw:N` pattern

**Currently implicit**: The hook does not validate the index structure. Phase 2
will add optional validation.

---

## Schema Split: Write-Input vs Stored Format

Alpha entries have **two distinct shapes**:

1. **Write-input format** (`alpha-entry.schema.json`, `convergence-web.schema.json`):
   The JSON payload sent to `buffer_manager.py alpha-write`. Includes fields
   like `key`, `maps_to`, `thesis`/`athesis` objects. This is what distill
   produces.

2. **Stored format** (entry sub-schema in `alpha-index.schema.json`):
   The shape of entries as stored in `index.json`. Has `source`, `file`,
   `concept`, optional `type`, `group`, `convergence_tag`. This is what
   buffer reads and sigma_hook queries.

`alpha-write` transforms write-input → stored format. The schemas validate
each side independently. `validate.py alpha-entry` validates stored entries
against the index entry sub-schema.

Framework entries (w:15–w:43) predate the current pipeline and may lack
`type` and `file` fields. The stored schema marks these as optional.

---

## Shared Utility

**File**: `schemas/normalize.py`

**Function**: `normalize_key(text: str) -> str`

Imported by:
- `distill/scripts/distill_manifest.py`
- `plugin/scripts/buffer_manager.py`

Both plugins MUST use this single implementation. See CONVENTIONS.md §3 for
the algorithm.

---

## Versioning

Changes to handoff schemas require:
1. Update the relevant `.schema.json` file
2. Update this contract document
3. Bump both plugin versions
4. Update CHANGELOG.md in both plugins
