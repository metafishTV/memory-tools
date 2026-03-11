# Full Mode + Alpha Reference — /buffer:off

> **Load condition**: Read this file only when `buffer_mode` is `"full"` AND `alpha/index.json` exists in the buffer directory. Lite mode and Full-without-alpha sessions do not need this content.

## Alpha Bin Tooling

Extends core `buffer_manager.py` for reference memory operations:

- `alpha-read --buffer-dir .claude/buffer/` — Read alpha bin index summary.
- `alpha-query --id/--source/--concept` — Retrieve referents by ID, source, or concept.
- `alpha-validate --buffer-dir .claude/buffer/` — Check alpha bin integrity.
- `alpha-write --buffer-dir .claude/buffer/` — Write new alpha entries (JSON on stdin).
- `alpha-delete --buffer-dir .claude/buffer/ --id w:N cw:N` — Remove entries + files.
- `next-id --layer warm` — Get next w:N ID (scans alpha to prevent collisions).

## changes.json: Concept Map Fields

In Full + Alpha mode, the changes.json schema includes additional fields:

```json
{
  "concept_map_changes": [{ "action": "add|update|flag|promote", "..." }],
  "convergence_web_changes": [{ "action": "add|update", "..." }],
  "validation_log_entries": [{ "check", "status", "detail", "session" }]
}
```

---

## Step 6: Validate Concept Map

> Runs after Step 5 (list open threads). Full + Alpha only.
>
> **Alpha gate:** Check if `alpha/` directory exists: `ls .claude/buffer/alpha/index.json 2>/dev/null`. If alpha bin does NOT exist — skip Steps 6 and 6b entirely. Concept map operations are deferred until the distill plugin provisions the alpha bin.

**Alpha-aware**: After migration, concept_map entries (cross_source, convergence_web, framework) live in the **alpha bin** (`alpha/` directory), not the warm layer. The warm layer retains only `decisions_archive` and `validation_log`.

1. Run `alpha-read --buffer-dir .claude/buffer/` to get the index summary
2. For each decision from Step 4, check if it touches a concept mapping:
   - If a mapping **changed**: update the alpha referent file directly, add to hot `concept_map_digest.recent_changes` with status `CHANGED`
   - If a **new concept** was introduced: use `alpha-write` to create it:
     ```bash
     echo '{"type":"cross_source","source_folder":"[kebab-case-source]","key":"Source:ConceptName","maps_to":"[mapping]","ref":"","suggest":null}' | scripts/buffer_manager.py alpha-write --buffer-dir .claude/buffer/
     ```
     Read the output JSON to get the assigned ID. Add to digest as `NEW`.
   - If a **suggestion was confirmed** by the user: update the referent file's `suggest` to `equiv`, log as `PROMOTED`
   - If a **foundational concept** was questioned: log as `NEEDS_USER_INPUT`, do NOT auto-change

3. Update `concept_map_digest._meta.total_entries` and `last_validated`
4. If alpha doesn't exist (pre-migration project), fall back to warm-layer concept_map operations

**IMPORTANT**: `suggest: null` is the PREFERRED state. Do NOT feel pressure to populate suggest fields. Only flag genuine structural parallels noticed during the session. The user must confirm any suggestion before it becomes an equiv.

---

## Step 6b: Consolidation

> Full + Alpha only. If alpha bin does NOT exist — skip this step entirely.

**Alpha-aware**: With reference memory in the alpha bin, consolidation operates differently:

**Warm layer consolidation** (decisions_archive + validation_log):
- Warm is now small (~274 lines). Consolidation means compressing verbose decision/validation entries using established vocabulary.
- Log all changes in `validation_log` with status `CONSOLIDATED`.

**Alpha referent consolidation** (individual .md files):
For alpha entries the current instance **created or meaningfully modified this session**:

- **Vocabulary compression**: Replace multi-word descriptions with established terms
- **Same-concept merge**: If two referent files describe the same structural relationship, merge into one file and delete the absorbed entry via `alpha-delete`:
     ```bash
     scripts/buffer_manager.py alpha-delete --buffer-dir .claude/buffer/ --id w:218
     ```
     Then update the surviving entry's `.md` file with merged content.
- **Description tightening**: Shorten explanatory prose to referential shorthand

Alpha files are self-contained and small (30-80 lines each), making targeted consolidation natural — edit a single file, update the index. No need to parse/rewrite large JSON arrays.

**Periodic deep consolidation** (at `full_scan_threshold`):

When `sessions_since_full_scan >= full_scan_threshold`, scan alpha index for:
1. Self-integrated entries -> apply deeper consolidation with confidence (automated)
2. Inherited entries -> identify candidates, **MANDATORY POPUP**: present proposals via `AskUserQuestion`, wait for the user's response — do NOT auto-approve
3. Apply ONLY the changes the user explicitly approved
4. Reset `sessions_since_full_scan` to 0

**Rules (all consolidation):**
- Never consolidate across source folders (folder boundaries are structural)
- Never auto-consolidate framework entries without `NEEDS_USER_INPUT`
- All consolidations logged in warm `validation_log` with status `CONSOLIDATED` and both entry IDs
- Absorbed entries: delete the file, remove from `alpha/index.json`
- When in doubt, don't merge — false merges lose meaning, missed merges just cost tokens

---

## Step 9 Extended: Tower Archival

> Part of conservation enforcement. Full mode only — Lite mode uses simplified conservation.

**If cold > 500 lines:**
- Trigger the archival questionnaire. Each step is a **MANDATORY POPUP**:

  **Questionnaire Step 1 — Full scan + dependency map:**
  Read entire cold layer. For each entry, compute nesting depth (how many other entries reference it). Present results via `AskUserQuestion` — show depth-0 entries marked as safe to archive and depth > 0 entries showing what references them. Wait for the user to acknowledge.

  **Questionnaire Step 2 — Pick ratio AND direction:**
  Present ratio choices via `AskUserQuestion` — options: 20/80, 33/66, 50/50. User also chooses which portion goes to the tower (smaller or larger). This is bidirectional — the user has full sovereignty. Wait for response.

  **Questionnaire Step 3 — Pick entries:**
  Present entry list via `AskUserQuestion`. User selects specific entries for archival, informed by the dependency map. Wait for response. Do NOT auto-select entries.

- Create a tower file: `handoff-tower-NNN-YYYY-MM-DD.json` in `.claude/buffer/`
- Leave tombstones in cold for archived entries:

  ```json
  {
    "id": "c:7",
    "archived_to": "tower-001",
    "was": "Brief description of archived entry",
    "session_archived": "YYYY-MM-DD"
  }
  ```

---

## Step 11: MEMORY.md Sync

Sync the project's MEMORY.md with current buffer state. Skip this step entirely if `memory_config` doesn't exist or `memory_config.integration` is `"none"`.

**Status sync** (if integration is `"full"` or `"lite"`):
- Read MEMORY.md at `memory_config.path`
- Find the `## Status` section
- Update to: `**Status**: [active_work.current_phase]. Next: [active_work.next_action].`
- If no `## Status` section exists, add one before `## Buffer Integration` (or at end of file)

**Promoted entry sync** (only if integration is `"full"` and promoted entries exist):
- Check warm entries with `"promoted_to_memory"` field
- If any changed since their promotion date: update the corresponding line in MEMORY.md's `## Stable Definitions` section
- If a promoted entry migrated to cold (now a tombstone): remove its line from `## Stable Definitions` and clear the `"promoted_to_memory"` field from the tombstone

This step is lightweight — at most a few line edits to MEMORY.md. It keeps the orientation card current without a full rewrite.

---

## Step 14b: Grid Rebuild (if alpha exists)

**Guard**: Only run if `alpha/index.json` exists in the buffer directory.

```bash
buffer_manager.py alpha-reinforce --buffer-dir .claude/buffer/
buffer_manager.py alpha-clusters --buffer-dir .claude/buffer/
buffer_manager.py alpha-grid-build --buffer-dir .claude/buffer/
```

Then amend the commit to include the updated grid:
```bash
git add .claude/buffer/alpha/index.json .claude/buffer/relevance_grid.json
git commit --amend --no-edit
```

This ensures the grid reflects the new session's orientation before the next `/buffer:on`.

If `remote_backup` is true in the hot layer, follow the commit with `git push`.

---

## Step 14c: Resolution Check (if alpha exists)

**Guard**: Only run if `alpha/index.json` exists in the buffer directory.

Run the resolution queue scanner to surface unresolved concept entries:

```bash
buffer_manager.py alpha-resolve --buffer-dir .claude/buffer/
```

If unresolved entries exist, print a brief summary after the grid rebuild:

```
Resolution queue: [N] unresolved entries ([M] ready, [K] awaiting design)
```

**Do NOT block** — this is informational only. The user decides whether to resolve now or defer. Do NOT auto-resolve. Do NOT prompt for resolution at session end — just surface the count so the user is aware.
