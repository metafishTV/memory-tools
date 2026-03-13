# Plugin Standardization Design — Schemas, Contracts, Validation

> Status: **approved**
> Date: 2026-03-12
> Scope: buffer 2.6.0 + distill 2.2.0 (Phase 1)
> Context: Comprehensive standardization pass across both plugins

---

## Problem

Format definitions are scattered across skill prompts, Python code, and
architecture docs. No machine-validatable schemas exist. The cross-plugin
interface (distill produces alpha entries that buffer consumes) has no formal
contract. Re-distillation has no "what changed" tracking, and the redistill
popup detection is broken (never fires). Concept key normalization is
duplicated between plugins.

## Design

### 1. Shared Schema Directory

**Location**: `session-buffer/schemas/`

Single source of truth for all data formats that cross plugin boundaries or
persist to disk.

| Schema File | Defines | Used By |
|---|---|---|
| `alpha-entry.schema.json` | w: entry structure (source, id, type, key, maps_to, ref) | buffer `alpha_write`, distill `integrate` |
| `convergence-web.schema.json` | cw: entry structure (tetradic: thesis, athesis, synthesis, metathesis) | buffer `alpha_write`, distill `integrate` |
| `alpha-index.schema.json` | index.json structure (entries, sources, concept_index, source_index, summary) | buffer sigma_hook, distill `integrate` |
| `manifest-source.schema.json` | Per-source manifest entry (concepts, metrics, forward_notes, cw_ids) | distill `distill_manifest.py` |
| `forward-note.schema.json` | Forward note entry (source, description, status, date) | distill `integrate` |
| `hot-layer.schema.json` | Hot layer JSON structure (session_meta, concept_map groups) | buffer `off` skill |
| `distill-stats.schema.json` | `.distill_stats` temporary file | distill `extract` + `analyze` |
| `redistill-changelog.schema.json` | `.redistill_changelog` diff file | distill `integrate` |

Schemas use JSON Schema draft 2020-12. Lightweight, well-supported by
Python's `jsonschema` library.

### 2. Cross-Plugin Contract

**File**: `schemas/CROSS_PLUGIN_CONTRACT.md`

Three handoff points:

**Handoff 1: Alpha Entry Creation** (distill `integrate` → buffer alpha bin)
- distill calls `buffer_manager.py alpha-write` with JSON payload
- Schema: `alpha-entry.schema.json` defines required/optional fields
- Concept key format: `Source:ConceptName`
- Source folder naming: `kebab-case(source_label)`

**Handoff 2: Convergence Web Edge Creation** (distill `integrate` → buffer alpha bin)
- Same `alpha-write` call with `type: convergence_web`
- Schema: `convergence-web.schema.json`
- Tetradic structure required: thesis/athesis/synthesis/metathesis all mandatory
- Synthesis tag vocabulary enumerated in schema:
  `[complementarity]`, `[independent_convergence]`, `[genealogy]`, `[elaboration]`

**Handoff 3: Sigma Hook Reads Alpha Index** (buffer sigma_hook → index.json)
- Schema: `alpha-index.schema.json`
- Currently implicit — hook assumes fields exist without checking

**Shared utility**: `schemas/normalize.py` — canonical `normalize_key()`
imported by both `distill_manifest.py` and `buffer_manager.py`.

### 3. Validation Tooling

**Script**: `schemas/validate.py`

```
python validate.py alpha-entry <path-to-index.json>
python validate.py manifest <path-to-manifest.json>
python validate.py distill-stats <path-to-.distill_stats>
python validate.py hot-layer <path-to-hot-layer.json>
python validate.py all <project-root>
```

Advisory only — surfaces problems for human review, does not gate writes.
Exit code 0 = clean, 1 = failures found.

Dependency: `jsonschema` library.

### 4. Re-distillation Improvements

**Bug fix**: Redistill popup detection in extract skill is broken (never
fires). Fix the path-checking logic.

**New artifact**: `.redistill_changelog` (JSON)

```json
{
  "source_label": "DeLanda_AssemblageTheory_2016_Book",
  "redistill_date": "2026-03-12",
  "mode": "update",
  "iteration": 2,
  "previous": {
    "date": "2026-02-28",
    "concept_count": 7,
    "concept_keys": ["parametrized_assemblage", "..."]
  },
  "current": {
    "concept_count": 21,
    "concept_keys": ["parametrized_assemblage", "...", "co_actualization"]
  },
  "diff": {
    "added": ["three_lines", "counter_actualization", "..."],
    "removed": [],
    "retained": ["parametrized_assemblage", "..."],
    "modified": []
  },
  "alpha_changes": {
    "new_ids": ["w:471", "..."],
    "updated_ids": [],
    "orphaned_ids": []
  }
}
```

Produced by `integrate` skill after alpha writes during re-distillation.
Consumed by `analyze` skill's interpretation summary (adds "Changes from
previous distillation" section).

**Manifest extension**: Add `redistill_history` field to per-source entries —
array of `{date, mode, concept_count, changelog_path}`.

### 5. CONVENTIONS.md

**File**: `schemas/CONVENTIONS.md`

Non-machine-validatable rules:

1. **Source Label Naming**: `Author_Title_Year_Type` — Type is one of
   `Book`, `Paper`, `Recording`, `Excerpt`, `Series`, `Table`
2. **Source Folder Naming**: `kebab-case(source_label)` — lowercase,
   underscores→hyphens
3. **Concept Key Normalization**: The `normalize_key()` algorithm —
   lowercase, strip parentheses, special chars→removed, spaces→underscores,
   max 40 chars
4. **ID Formatting**: `w:N` (cross-source), `cw:N` (convergence web),
   `c:N` (cold layer). File padding: 3 digits. Sequence global, never reused
5. **Convergence Web Synthesis Tags**: `[complementarity]`,
   `[independent_convergence]`, `[genealogy]`, `[elaboration]` with
   definitions
6. **Relationship Types**: `confirms`, `extends`, `challenges`, `novel`
   with criteria
7. **Distillation Voice Rules**: Direct assertive register. No meta-
   commentary. Attribution structural, not prose-embedded
8. **Atom Marker Format**: `<!-- SECTION:name -->`, `<!-- CONCEPT:key -->`,
   `<!-- FIGURE:id -->` with matching close tags

## Files to Modify

| File | Action | Est. Lines |
|---|---|---|
| `schemas/` (new dir) | CREATE — 8 schema files | ~400 |
| `schemas/normalize.py` | CREATE — shared normalize_key() | ~30 |
| `schemas/validate.py` | CREATE — validation script | ~200 |
| `schemas/CONVENTIONS.md` | CREATE — human-readable rules | ~150 |
| `schemas/CROSS_PLUGIN_CONTRACT.md` | CREATE — handoff spec | ~80 |
| `distill/scripts/distill_manifest.py` | MODIFY — import from schemas/ | ~5 |
| `plugin/scripts/buffer_manager.py` | MODIFY — import from schemas/ | ~5 |
| `distill/skills/extract/SKILL.md` | MODIFY — fix redistill popup | ~20 |
| `distill/skills/integrate/SKILL.md` | MODIFY — add changelog generation | ~30 |
| `tests/test_validate.py` | CREATE | ~150 |
| `tests/test_normalize.py` | CREATE | ~50 |
| `tests/test_redistill_changelog.py` | CREATE | ~60 |
| `plugin/.claude-plugin/plugin.json` | MODIFY — 2.5.0 → 2.6.0 | 1 |
| `distill/plugin/.claude-plugin/plugin.json` | MODIFY — 2.1.0 → 2.2.0 | 1 |
| `CHANGELOG.md` | MODIFY — add entries | ~20 |

## Test Plan

| Test Class | Tests | Covers |
|---|---|---|
| `TestNormalizeKey` | 5 | Parentheses, special chars, truncation, empty, unicode |
| `TestAlphaEntrySchema` | 4 | Valid entry, missing required, extra fields, type enum |
| `TestConvergenceWebSchema` | 4 | Valid cw, missing tetradic field, invalid tag, valid tags |
| `TestAlphaIndexSchema` | 3 | Valid index, missing summary, malformed entries |
| `TestManifestSourceSchema` | 3 | Valid source, missing concepts, invalid relationship |
| `TestForwardNoteSchema` | 2 | Valid note, missing required |
| `TestHotLayerSchema` | 3 | Valid hot layer, missing session_meta, malformed groups |
| `TestDistillStatsSchema` | 2 | Valid stats, missing pages |
| `TestRedistillChangelog` | 3 | Valid changelog, diff computation, empty previous |
| `TestValidateAll` | 3 | Full project scan, mixed pass/fail, empty project |

~32 tests total.

## Phase 2 (Future)

- Schema validation integrated into `alpha_write` as `--validate` flag
- Hot/warm/cold layer validation in `/buffer:off`
- Distillation compliance checker (structural — sections, markers, table format)

## Verification

1. All existing tests pass (398 buffer + distill tests)
2. All ~32 new tests pass
3. `validate.py all` runs clean against sigma-TAP-repo
4. Manual test: run a distillation, verify changelog generated
5. Manual test: trigger redistill popup on existing source
6. Verify `normalize_key()` import works from both plugins
