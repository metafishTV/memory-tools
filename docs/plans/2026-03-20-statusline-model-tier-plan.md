# Statusline Enhancement + Model Tier Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an enhanced statusline as a plugin feature with model tier detection, football state, and tier-scaled compaction — plus a `buffer:status` skill as a universal fallback for desktop app users.

**Architecture:** Add `detect_model()` to `buffer_utils.py` as the shared model-tier function. Replace the plugin's dead `statusline.py` with an enhanced version based on the user's standalone `~/.claude/statusline.py`. Add tier parameter to `compact_hook.py`'s summary/directive functions. Extend the existing `buffer:status` skill. Create a `buffer:setup-statusline` skill for opt-in configuration.

**Tech Stack:** Python 3, Claude Code statusline stdin JSON API, `~/.claude/settings.json` for model detection.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `plugin/scripts/buffer_utils.py` | Modify | Add `detect_model()` + `read_football_registry()` |
| `plugin/scripts/statusline.py` | Enhance | Full-featured statusline (model, buffer, git, football, context). Preserve existing headroom detection. |
| `plugin/scripts/compact_hook.py` | Modify | Tier-scaled `build_compact_summary()` and `generate_directive_context()` |
| `plugin/skills/status/SKILL.md` | Rewrite | Enhanced status report with model tier, football, staleness |
| `plugin/skills/setup-statusline/SKILL.md` | Create | Opt-in statusline configuration skill |
| `plugin/skills/on/SKILL.md` | Modify | Add first-run statusline notice |

---

### Task 1: Add `detect_model()` and `read_football_registry()` to buffer_utils.py

**Files:**
- Modify: `plugin/scripts/buffer_utils.py`

These are shared utilities needed by both statusline.py and compact_hook.py.

**Important context:** The active model is NOT stored in `~/.claude/settings.json`. It's runtime state, delivered via stdin JSON to the statusline script as `model.display_name`. The statusline writes the detected model+tier to a state file (`~/.claude/buffer/.model_tier`) on every invocation. Other scripts (compact_hook.py, buffer:status skill) read that file.

- [ ] **Step 1: Add `model_tier_from_name()` and `read_model_tier()` functions**

Append to `buffer_utils.py`:

```python
MODEL_TIER_PATH = os.path.join(
    os.path.expanduser('~'), '.claude', 'buffer', '.model_tier')


def model_tier_from_name(display_name):
    """Map a model display name to a tier.

    Tier mapping:
      opus   -> 'full'
      sonnet -> 'moderate'
      haiku  -> 'lean'
      unknown -> 'full' (safe fallback)
    """
    if not display_name:
        return 'full'
    name_lower = display_name.lower()
    if 'opus' in name_lower:
        return 'full'
    elif 'sonnet' in name_lower:
        return 'moderate'
    elif 'haiku' in name_lower:
        return 'lean'
    return 'full'


def write_model_tier(display_name, tier, path=None):
    """Write current model+tier to state file. Called by statusline on every turn."""
    if path is None:
        path = MODEL_TIER_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'model': display_name, 'tier': tier}, f)
    except OSError:
        pass


def read_model_tier(path=None):
    """Read model+tier from state file. Returns (model_name, tier).

    Fail-safe: returns ('unknown', 'full') on any error.
    """
    if path is None:
        path = MODEL_TIER_PATH
    data = _read_json(path)
    if data and 'tier' in data:
        return (data.get('model', 'unknown'), data.get('tier', 'full'))
    return ('unknown', 'full')
```

- [ ] **Step 2: Add `read_football_registry()` function**

Append to `buffer_utils.py`:

```python
FOOTBALL_REGISTRY_PATH = os.path.join(
    os.path.expanduser('~'), '.claude', 'buffer', 'football-registry.json')


def read_football_registry(path=None):
    """Read global football registry. Returns dict with 'balls' key, or empty."""
    if path is None:
        path = FOOTBALL_REGISTRY_PATH
    data = _read_json(path)
    if not data or not isinstance(data, dict):
        return {'balls': {}}
    return data
```

- [ ] **Step 3: Verify import**

Run: `python -c "import sys; sys.path.insert(0, 'plugin/scripts'); import buffer_utils; print(buffer_utils.detect_model()); print(len(buffer_utils.read_football_registry().get('balls', {})))"`

Expected: `('claude-opus-4-6', 'full')` (or similar) and a ball count.

- [ ] **Step 4: Commit**

```bash
git add plugin/scripts/buffer_utils.py
git commit -m "feat: add detect_model() and read_football_registry() to buffer_utils"
```

---

### Task 2: Rewrite plugin statusline.py

**Files:**
- Rewrite: `plugin/scripts/statusline.py`

Enhance the plugin's statusline.py using the user's standalone `~/.claude/statusline.py` as reference. The existing plugin version has working headroom tier detection and telemetry — preserve that. Key additions: model tier, football state, `find_buffer_dir()` (fixes CWD bug), ANSI colors, two-line format, cost/duration/cache from stdin.

- [ ] **Step 0: Read reference files**

Read both statusline implementations before writing:
- `~/.claude/statusline.py` — the standalone (ANSI colors, git subprocess, cache ratio, cost, two-line format)
- `plugin/scripts/statusline.py` — the plugin version (headroom detection, telemetry, single-line format)

Merge the best of both. Preserve `_detect_headroom()` and telemetry integration from the plugin version. Take the two-line ANSI format, git info, cost display from the standalone.

- [ ] **Step 1: Write the enhanced statusline.py**

The script must:
- Read JSON from stdin (Claude Code provides model, context_window, cost, cwd, etc.)
- Use `find_buffer_dir()` from buffer_utils (not CWD-relative) for buffer discovery
- Use `model_tier_from_name()` from buffer_utils to compute tier from stdin `model.display_name`
- Call `write_model_tier()` on every invocation to persist model+tier for other scripts (compact_hook, etc.)
- Use `read_football_registry()` from buffer_utils for football count
- Output two lines with ANSI color (matching standalone format)
- Run headroom tier detection (preserve existing telemetry integration)
- Never crash — all reads wrapped in try/except

**Line 1 segments** (pipe-separated):
- `[Model (tier)]` — e.g. `[Opus 4.6 (full)]` or `[Sonnet 4.5 (moderate)]`
- Directory name
- Git branch + staged/modified counts
- `buf:{mode}` + `thr:N` + `distill` + `compacted` markers
- `fb:N` — football count (only if >0 in-flight or caught)

**Line 2 segments** (pipe-separated):
- Context bar with color thresholds (`#-------- 11%`)
- Extended context indicator (`1M` if >200k window)
- Cache ratio (`cache:96%`)
- Cost (`$5.06`)
- Duration (`57m 27s`)
- Lines added/removed (`+88-23`)

Implementation note: use `importlib.util` to load `buffer_utils.py`, `telemetry.py` from sibling directory — same pattern as other plugin scripts. Fall back gracefully if imports fail.

- [ ] **Step 2: Test with simulated stdin**

```bash
echo '{"model":{"display_name":"Opus 4.6"},"cwd":"C:/Users/user/Documents/New folder/sigma-TAP-repo","context_window":{"used_percentage":45,"context_window_size":1000000,"current_usage":{"cache_read_input_tokens":90000,"cache_creation_input_tokens":5000,"input_tokens":5000}},"cost":{"total_cost_usd":3.50,"total_duration_ms":180000,"total_lines_added":50,"total_lines_removed":10}}' | python plugin/scripts/statusline.py
```

Expected: Two-line colored output with model tier, buffer state, git branch, context bar, cost.

- [ ] **Step 3: Test with no buffer dir (fallback)**

```bash
echo '{"model":{"display_name":"Sonnet 4.5"},"cwd":"C:/tmp","context_window":{"used_percentage":10}}' | python plugin/scripts/statusline.py
```

Expected: `[Sonnet 4.5 (moderate)] tmp | buf:off` (no crash, graceful degradation).

- [ ] **Step 4: Commit**

```bash
git add plugin/scripts/statusline.py
git commit -m "feat: enhanced statusline with model tier, football state, buffer discovery"
```

---

### Task 3: Tier-scaled compaction in compact_hook.py

**Files:**
- Modify: `plugin/scripts/compact_hook.py`

This is the original football task. Add tier parameter to `build_compact_summary()` and `generate_directive_context()`.

- [ ] **Step 1: Read compact_hook.py and identify the call chain**

Read the source repo copy (`plugin/scripts/compact_hook.py`). Map the actual call chain:
- `cmd_post_compact()` calls `build_compact_summary()`
- `build_compact_summary()` internally calls `generate_directive_context()`
- `cmd_pre_compact()` emits telemetry

Note: compact_hook.py loads buffer_utils via `importlib.util` (not standard import). Use the same pattern to access `read_model_tier`:

```python
# Near the top, alongside existing buffer_utils loading:
_read_model_tier = None
try:
    _read_model_tier = _utils.read_model_tier  # _utils is the already-loaded buffer_utils module
except AttributeError:
    pass

def _get_tier():
    """Get current model tier. Reads from state file written by statusline."""
    if _read_model_tier:
        _, tier = _read_model_tier()
        return tier
    return 'full'
```

- [ ] **Step 2: Add tier parameter to build_compact_summary()**

Modify signature: add `tier='full'` default parameter.

**Tier scaling:**

`full` (opus): Current behavior unchanged.

`moderate` (sonnet):
- Skip `## Session Narrative` section entirely
- Trim briefing excerpt from 20 lines to 10
- Trim instance notes remarks from 5 to 3
- Trim open questions from 3 to 2

`lean` (haiku):
- Render ONLY: session state line, active work, orientation, open threads, natural summary, layer sizes
- Skip: briefing, narrative, instance notes, concept map digest, convergence web digest, memory config
- Trim open threads to status + thread text only (no refs)
- Trim recent decisions to last 2 (not 3)

**Critical:** `build_compact_summary()` internally calls `generate_directive_context()`. It must forward the `tier` parameter to that call.

- [ ] **Step 3: Add tier parameter to generate_directive_context()**

Modify signature: add `tier='full'` default parameter.

`full`: Current behavior.
`moderate`: Skip vocabulary section.
`lean`: Only render active threads + session depth line. Skip on-disk paths, vocabulary.

- [ ] **Step 4: Wire through cmd_post_compact()**

`cmd_post_compact()` is the entry point. It calls `build_compact_summary()` which internally calls `generate_directive_context()`. Only one wiring point needed:

```python
tier = _get_tier()
context = build_compact_summary(hot, buffer_dir, hot_max, warm_max, cold_max, tier=tier)
```

Do NOT add a separate `generate_directive_context()` call — it's already called inside `build_compact_summary()` and receives tier from there.

- [ ] **Step 5: Add model_tier to pre-compact telemetry**

In `cmd_pre_compact()`, after detecting model:
```python
tier = _get_tier()
# Add to existing telemetry event dict:
event['model_tier'] = tier
```

- [ ] **Step 6: Verify import and regression**

```bash
python -c "import sys; sys.path.insert(0, 'plugin/scripts'); import compact_hook; print('OK')"
```

- [ ] **Step 7: Commit**

```bash
git add plugin/scripts/compact_hook.py
git commit -m "feat: tier-scaled compaction summaries for sonnet/haiku context efficiency"
```

---

### Task 4: Enhance buffer:status skill

**Files:**
- Rewrite: `plugin/skills/status/SKILL.md`

Add model tier, football state, save staleness, and mismatch notice. This is the universal fallback that works everywhere including desktop app.

- [ ] **Step 1: Rewrite SKILL.md**

The skill should instruct Claude to:

1. Read `~/.claude/settings.json` for model + tier
2. Read `~/.claude/buffer/football-registry.json` for football state
3. Read `.claude/buffer/handoff.json` for session state (via `find_buffer_dir` or walk-up)
4. Read `.claude/buffer/.session_active` for session depth
5. Check marker files (distill, compact, sigma)
6. Check compaction directives
7. Estimate context health (Claude's self-awareness)

Output format — single block:

```
Session Health
─────────────
Model:       Opus 4.6 → full tier
Buffer:      on | full mode | saved 2026-03-19 (1 day ago)
Phase:       cross-layer reconciliation
Threads:     3 open
Depth:       2 save cycles

Context:     ~45% used [green]
Markers:     none
Directives:  active (12 files, 3 threads, 8 vocab)

Footballs:   1 in-flight, 1 returned
             ├ 0320-reconciliation-audit (in-flight, 2026-03-20)
             └ 0319-classify-individual.. (returned, 2026-03-20)

Recommendation: Healthy. Continue working.
```

Add model mismatch notice: if tier is `moderate` or `lean`, append:
```
⚠ Running on [Sonnet/Haiku] — compact summaries are trimmed for context efficiency.
  Switch to Opus for full recovery detail after compaction.
```

- [ ] **Step 2: Commit**

```bash
git add plugin/skills/status/SKILL.md
git commit -m "feat: enhanced buffer:status with model tier, football state, staleness"
```

---

### Task 5: Create buffer:setup-statusline skill

**Files:**
- Create: `plugin/skills/setup-statusline/SKILL.md`

Opt-in skill that configures the plugin's statusline in the user's settings.json.

- [ ] **Step 1: Write SKILL.md**

The skill should:

1. Read `~/.claude/settings.json`
2. Check if `statusLine` is already configured
3. If not configured: show the user what will be added, ask for confirmation, then write it
4. If configured and points to the plugin: update path, confirm
5. If configured and points to something else: show current config, explain what the plugin's statusline offers, ask if they want to switch (with option to back up current)

The statusLine config to write:
```json
{
  "statusLine": {
    "type": "command",
    "command": "python \"<PLUGIN_ROOT>/scripts/statusline.py\""
  }
}
```

Where `<PLUGIN_ROOT>` is resolved from `${CLAUDE_PLUGIN_ROOT}` — the skill should instruct Claude to read the plugin root from the skill's base directory path.

Important: the skill must use `AskUserQuestion` before modifying settings.json. FULL STOP protocol applies.

- [ ] **Step 2: Commit**

```bash
git add plugin/skills/setup-statusline/SKILL.md
git commit -m "feat: buffer:setup-statusline skill for opt-in statusline configuration"
```

---

### Task 6: Add statusline notice to /buffer:on first-run

**Files:**
- Modify: `plugin/skills/on/SKILL.md`

- [ ] **Step 1: Add notice to first-run detection block**

In the existing first-run detection section of `/buffer:on`, add after the first-run setup completes:

```
If no statusline is configured (check ~/.claude/settings.json for statusLine field):
  "Tip: Run /buffer:setup-statusline to enable the buffer statusline — shows model tier, context pressure, football state, and buffer mode at a glance."
```

This is a one-time notice, not a gate. Don't block the on process.

- [ ] **Step 2: Commit**

```bash
git add plugin/skills/on/SKILL.md
git commit -m "feat: first-run statusline notice in /buffer:on"
```

---

### Task 7: Version bump + release

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json` → 3.9.0
- Modify: `.claude-plugin/marketplace.json` → 3.9.0, lastUpdated
- Modify: `plugin/skills/on/SKILL.md` → version string
- Modify: `CHANGELOG.md` → new entry
- Create: `buffer-v3.9.0.zip`

Note: 3.9.0 (not 3.8.2) because this is a feature addition, not a patch.

- [ ] **Step 1: Bump version in all 4 locations**

Per CLAUDE.md checklist:
1. `plugin/.claude-plugin/plugin.json` → `"version": "3.9.0"`
2. `plugin/skills/on/SKILL.md` → `buffer v3.9.0 |`
3. `.claude-plugin/marketplace.json` → version + lastUpdated
4. `CHANGELOG.md` → new section

- [ ] **Step 2: Write CHANGELOG entry**

```markdown
## [buffer 3.9.0] - 2026-03-20

### Model tier detection + adaptive scaling
- **`detect_model()`** — shared utility in buffer_utils.py. Reads ~/.claude/settings.json, maps to tier (opus→full, sonnet→moderate, haiku→lean). Fail-safe: defaults to full.
- **Tier-scaled compaction** — `build_compact_summary()` and `generate_directive_context()` in compact_hook.py now accept a `tier` parameter. Sonnet gets trimmed sections, Haiku gets minimal recovery context. Opus unchanged.
- **`model_tier` in telemetry** — pre-compact telemetry events now include the active model tier.

### Enhanced statusline
- **Plugin-shipped statusline** — full-featured statusline.py replaces the previous unused stub. Shows model+tier, buffer mode, football count, git branch+changes, context bar, cache ratio, cost, duration, lines changed.
- **`find_buffer_dir()` discovery** — statusline uses registry-based buffer discovery instead of CWD-relative. Fixes `buf:--` when working in subdirectories or sibling repos.
- **`/buffer:setup-statusline`** — opt-in skill to configure the plugin's statusline in settings.json. Detects existing statusline config and asks before overwriting.

### Enhanced buffer:status
- **Model tier + mismatch warning** — shows active model, tier, and warns if not on Opus.
- **Football state** — shows in-flight, caught, returned balls with IDs and dates.
- **Save staleness** — flags handoffs older than 2 days.
- **Session depth** — shows save/restore cycle count.
```

- [ ] **Step 3: Build zip**

```bash
cd plugin && python -c "
import zipfile, os
zf = zipfile.ZipFile('../buffer-v3.9.0.zip', 'w', zipfile.ZIP_DEFLATED)
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
    for f in files:
        if f.endswith('.pyc'): continue
        fp = os.path.join(root, f)
        zf.write(fp, fp[2:])
zf.close()
"
```

- [ ] **Step 4: Commit and push**

```bash
git add -f buffer-v3.9.0.zip
git add plugin/ .claude-plugin/marketplace.json CHANGELOG.md
git commit -m "feat: model tier detection, enhanced statusline, buffer:status (v3.9.0)"
git tag v3.9.0
git push origin master --tags
```

- [ ] **Step 5: Copy to cache**

Note: Adjust the cache version directory to match your installed version.

```bash
CACHE=~/.claude/plugins/cache/memory-tools-by-metafish/buffer/3.8.0
cp plugin/scripts/statusline.py "$CACHE/scripts/"
cp plugin/scripts/buffer_utils.py "$CACHE/scripts/"
cp plugin/scripts/compact_hook.py "$CACHE/scripts/"
cp plugin/skills/status/SKILL.md "$CACHE/skills/status/"
mkdir -p "$CACHE/skills/setup-statusline"
cp plugin/skills/setup-statusline/SKILL.md "$CACHE/skills/setup-statusline/"
```

- [ ] **Step 6: Code review**

Dispatch `superpowers:code-reviewer` against the full set of changes before claiming completion. Review scope: all modified/created files in Tasks 1-6.
