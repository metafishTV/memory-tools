# Registry-Primary Discovery & Buffer Migration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace walk-up-only buffer discovery with registry-primary lookup + git-guarded fallback, rewrite SKILL.md Step 0 for subdirectory scanning, and migrate sigma-TAP buffer to its git repo.

**Architecture:** New shared module `buffer_utils.py` provides `find_buffer_dir()` (registry + git-guarded walk-up), imported by both hooks via `importlib`. SKILL.md Step 0 gets smart discovery with scoring. `projects.json` v2 adds `repo_root` field. Migration is a one-time file copy + cleanup.

**Tech Stack:** Python 3 (hooks), Markdown (SKILL.md), pytest (tests), bash (migration)

**Spec:** `docs/superpowers/specs/2026-03-14-registry-discovery-migration-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `plugin/scripts/buffer_utils.py` | CREATE | Shared discovery: `find_buffer_dir`, `read_registry`, `match_cwd_to_project`, `is_git_repo` |
| `plugin/scripts/sigma_hook.py` | MODIFY (lines 169-179) | Replace `find_buffer_dir` with import from `buffer_utils` |
| `plugin/scripts/compact_hook.py` | MODIFY (lines 32-42) | Replace `find_buffer_dir` with import from `buffer_utils` |
| `plugin/skills/on/SKILL.md` | MODIFY (lines 48-146) | Rewrite Step 0a-0e for smart discovery |
| `plugin/skills/off/SKILL.md` | MODIFY (lines 323-342) | Update Step 12 to v2 schema |
| `tests/test_buffer_utils.py` | CREATE | Tests for all buffer_utils functions |
| `tests/test_compact_hook.py` | MODIFY | Update tests that set up buffer dirs without `.git` |

---

## Chunk 1: buffer_utils.py + Tests (TDD)

### Task 1: Write tests for `is_git_repo`

**Files:**
- Create: `tests/test_buffer_utils.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for buffer_utils — shared hook discovery utilities."""
import os
import json
import pytest
from unittest.mock import patch

# Import will fail until we create the module
import importlib.util
_spec = importlib.util.spec_from_file_location(
    'buffer_utils',
    os.path.join(os.path.dirname(__file__), '..', 'plugin', 'scripts', 'buffer_utils.py'))
buffer_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(buffer_utils)


class TestIsGitRepo:
    def test_directory_with_dot_git(self, tmp_path):
        (tmp_path / '.git').mkdir()
        assert buffer_utils.is_git_repo(str(tmp_path)) is True

    def test_directory_without_dot_git(self, tmp_path):
        assert buffer_utils.is_git_repo(str(tmp_path)) is False

    def test_nonexistent_directory(self, tmp_path):
        assert buffer_utils.is_git_repo(str(tmp_path / 'nope')) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py::TestIsGitRepo -v`
Expected: FAIL (ModuleNotFoundError or ImportError — buffer_utils.py doesn't exist yet)

- [ ] **Step 3: Create buffer_utils.py with `is_git_repo`**

```python
#!/usr/bin/env python3
"""
Session Buffer — Shared Discovery Utilities

Provides buffer directory discovery for hook scripts (sigma_hook, compact_hook).
Registry-primary lookup with git-guarded walk-up fallback.

Import via importlib (see sigma_hook.py for pattern):
    spec = importlib.util.spec_from_file_location(
        'buffer_utils', os.path.join(script_dir, 'buffer_utils.py'))
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
"""

import os
import json


# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------

REGISTRY_PATH = os.path.join(os.path.expanduser('~'), '.claude', 'buffer', 'projects.json')


def is_git_repo(path):
    """Check if path is a git repo root (has .git/ directory)."""
    try:
        return os.path.isdir(os.path.join(path, '.git'))
    except (TypeError, OSError):
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py::TestIsGitRepo -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
cd session-buffer
git add plugin/scripts/buffer_utils.py tests/test_buffer_utils.py
git commit -m "feat: add buffer_utils.py with is_git_repo"
```

---

### Task 2: Write tests for `match_cwd_to_project` and implement

**Files:**
- Modify: `tests/test_buffer_utils.py`
- Modify: `plugin/scripts/buffer_utils.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_buffer_utils.py`:

```python
class TestMatchCwdToProject:
    def test_cwd_equals_repo_root(self):
        assert buffer_utils.match_cwd_to_project('/home/user/proj', '/home/user/proj') is True

    def test_cwd_inside_repo(self):
        assert buffer_utils.match_cwd_to_project('/home/user/proj/src/lib', '/home/user/proj') is True

    def test_cwd_is_parent_of_repo(self):
        assert buffer_utils.match_cwd_to_project('/home/user', '/home/user/proj') is False

    def test_cwd_unrelated(self):
        assert buffer_utils.match_cwd_to_project('/tmp/other', '/home/user/proj') is False

    def test_prefix_collision_blocked(self):
        """repo_root=/proj must NOT match cwd=/project-2."""
        assert buffer_utils.match_cwd_to_project('/project-2', '/proj') is False

    @pytest.mark.skipif(os.name != 'nt', reason='Windows-only')
    def test_windows_case_insensitive(self):
        assert buffer_utils.match_cwd_to_project(
            'c:\\Users\\user\\proj', 'C:\\Users\\user\\proj') is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py::TestMatchCwdToProject -v`
Expected: FAIL (AttributeError — function doesn't exist)

- [ ] **Step 3: Implement `match_cwd_to_project`**

Add to `plugin/scripts/buffer_utils.py`:

```python
def match_cwd_to_project(cwd, repo_root):
    """Check if cwd is inside (or equal to) repo_root.

    Uses os.path.normcase for Windows case-insensitivity.
    Trailing separator guard prevents /proj matching /project-2.
    """
    norm_cwd = os.path.normcase(os.path.abspath(cwd))
    norm_root = os.path.normcase(os.path.abspath(repo_root))
    if norm_cwd == norm_root:
        return True
    return norm_cwd.startswith(norm_root + os.sep)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py::TestMatchCwdToProject -v`
Expected: 5-6 PASSED (6 on Windows, 5 on non-Windows with skip)

- [ ] **Step 5: Commit**

```bash
cd session-buffer
git add plugin/scripts/buffer_utils.py tests/test_buffer_utils.py
git commit -m "feat: add match_cwd_to_project with path normalization"
```

---

### Task 3: Write tests for `read_registry` (v1→v2 upgrade) and implement

**Files:**
- Modify: `tests/test_buffer_utils.py`
- Modify: `plugin/scripts/buffer_utils.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_buffer_utils.py`:

```python
class TestReadRegistry:
    def test_no_file_returns_empty(self, tmp_path):
        result = buffer_utils.read_registry(str(tmp_path / 'nonexistent.json'))
        assert result == {'schema_version': 2, 'projects': {}}

    def test_reads_v2_as_is(self, tmp_path):
        reg = {
            'schema_version': 2,
            'projects': {
                'myproj': {
                    'repo_root': '/home/user/myproj',
                    'buffer_path': '/home/user/myproj/.claude/buffer',
                    'scope': 'full',
                    'last_handoff': '2026-03-14'
                }
            }
        }
        path = tmp_path / 'projects.json'
        path.write_text(json.dumps(reg), encoding='utf-8')
        result = buffer_utils.read_registry(str(path))
        assert result['schema_version'] == 2
        assert result['projects']['myproj']['repo_root'] == '/home/user/myproj'

    def test_upgrades_v1_to_v2(self, tmp_path):
        reg = {
            'schema_version': 1,
            'projects': {
                'myproj': {
                    'buffer_path': '/home/user/myproj/.claude/buffer',
                    'scope': 'full',
                    'last_handoff': '2026-03-10',
                    'remote_backup': True,
                    'project_context': 'test project'
                }
            }
        }
        path = tmp_path / 'projects.json'
        path.write_text(json.dumps(reg), encoding='utf-8')
        result = buffer_utils.read_registry(str(path))
        assert result['schema_version'] == 2
        proj = result['projects']['myproj']
        assert proj['repo_root'] == '/home/user/myproj'
        assert proj['scope'] == 'full'
        assert proj['remote_backup'] is True
        assert proj['project_context'] == 'test project'
        assert proj['last_handoff'] == '2026-03-10'

    def test_v1_upgrade_strips_buffer_suffix(self, tmp_path):
        """Windows-style path with backslashes."""
        reg = {
            'schema_version': 1,
            'projects': {
                'winproj': {
                    'buffer_path': 'C:\\Users\\user\\proj\\.claude\\buffer',
                    'scope': 'lite'
                }
            }
        }
        path = tmp_path / 'projects.json'
        path.write_text(json.dumps(reg), encoding='utf-8')
        result = buffer_utils.read_registry(str(path))
        proj = result['projects']['winproj']
        # Should strip \.claude\buffer or /.claude/buffer
        assert '.claude' not in proj['repo_root']
        assert 'buffer' not in proj['repo_root']

    def test_corrupt_json_returns_empty(self, tmp_path):
        path = tmp_path / 'projects.json'
        path.write_text('not json', encoding='utf-8')
        result = buffer_utils.read_registry(str(path))
        assert result == {'schema_version': 2, 'projects': {}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py::TestReadRegistry -v`
Expected: FAIL

- [ ] **Step 3: Implement `read_registry`**

Add to `plugin/scripts/buffer_utils.py`:

```python
def _read_json(path):
    """Read JSON file, return dict or None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _infer_repo_root(buffer_path):
    """Strip /.claude/buffer or \\.claude\\buffer suffix to get repo root."""
    # Normalize to forward slashes for stripping, then convert back
    normalized = buffer_path.replace('\\', '/')
    for suffix in ['/.claude/buffer/', '/.claude/buffer']:
        if normalized.endswith(suffix):
            root = normalized[:-len(suffix)]
            # Restore original separator style
            if '\\' in buffer_path:
                return root.replace('/', '\\')
            return root
    # Fallback: warn and return as-is (malformed path)
    import sys as _sys
    print(f"buffer_utils: could not strip .claude/buffer suffix from: {buffer_path}",
          file=_sys.stderr)
    return buffer_path


def read_registry(path=None):
    """Read projects.json, auto-upgrading v1 to v2.

    Preserves all existing fields during upgrade (scope, remote_backup, etc).
    Returns empty v2 registry if file doesn't exist or is corrupt.
    """
    if path is None:
        path = REGISTRY_PATH

    data = _read_json(path)
    if not data or not isinstance(data, dict):
        return {'schema_version': 2, 'projects': {}}

    version = data.get('schema_version', 1)
    projects = data.get('projects', {})

    if version < 2:
        # Upgrade: infer repo_root from buffer_path for each project
        for name, proj in projects.items():
            if 'repo_root' not in proj and 'buffer_path' in proj:
                proj['repo_root'] = _infer_repo_root(proj['buffer_path'])
        data['schema_version'] = 2

    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py::TestReadRegistry -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
cd session-buffer
git add plugin/scripts/buffer_utils.py tests/test_buffer_utils.py
git commit -m "feat: add read_registry with v1-to-v2 auto-upgrade"
```

---

### Task 4: Write tests for `find_buffer_dir` (registry + git-guarded walk-up) and implement

**Files:**
- Modify: `tests/test_buffer_utils.py`
- Modify: `plugin/scripts/buffer_utils.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_buffer_utils.py`:

```python
class TestFindBufferDir:
    def _make_buffer(self, root):
        """Create a minimal buffer dir with handoff.json."""
        buf = root / '.claude' / 'buffer'
        buf.mkdir(parents=True)
        (buf / 'handoff.json').write_text('{}', encoding='utf-8')
        return buf

    def _make_git_repo(self, root):
        """Add a .git directory to make it look like a git repo."""
        (root / '.git').mkdir(exist_ok=True)

    def _make_registry(self, reg_path, projects):
        """Write a v2 projects.json."""
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        data = {'schema_version': 2, 'projects': projects}
        reg_path.write_text(json.dumps(data), encoding='utf-8')

    def test_registry_match_returns_buffer_path(self, tmp_path):
        repo = tmp_path / 'myrepo'
        repo.mkdir()
        self._make_git_repo(repo)
        buf = self._make_buffer(repo)
        reg_path = tmp_path / 'registry.json'
        self._make_registry(reg_path, {
            'myproj': {
                'repo_root': str(repo),
                'buffer_path': str(buf),
            }
        })
        result = buffer_utils.find_buffer_dir(str(repo), registry_path=str(reg_path))
        assert result == str(buf)

    def test_registry_match_cwd_inside_repo(self, tmp_path):
        repo = tmp_path / 'myrepo'
        subdir = repo / 'src' / 'lib'
        subdir.mkdir(parents=True)
        self._make_git_repo(repo)
        buf = self._make_buffer(repo)
        reg_path = tmp_path / 'registry.json'
        self._make_registry(reg_path, {
            'myproj': {
                'repo_root': str(repo),
                'buffer_path': str(buf),
            }
        })
        result = buffer_utils.find_buffer_dir(str(subdir), registry_path=str(reg_path))
        assert result == str(buf)

    def test_walkup_finds_buffer_in_git_repo(self, tmp_path):
        """No registry match, but walk-up finds buffer in a git repo."""
        repo = tmp_path / 'myrepo'
        repo.mkdir()
        self._make_git_repo(repo)
        buf = self._make_buffer(repo)
        reg_path = tmp_path / 'empty_registry.json'
        # No registry file — forces fallback
        result = buffer_utils.find_buffer_dir(str(repo), registry_path=str(reg_path))
        assert result == str(buf)

    def test_walkup_rejects_buffer_in_non_git_dir(self, tmp_path):
        """Buffer exists but directory is NOT a git repo — should be rejected."""
        non_git = tmp_path / 'workspace'
        non_git.mkdir()
        self._make_buffer(non_git)  # buffer exists but no .git
        reg_path = tmp_path / 'empty_registry.json'
        result = buffer_utils.find_buffer_dir(str(non_git), registry_path=str(reg_path))
        assert result is None

    def test_no_buffer_anywhere_returns_none(self, tmp_path):
        reg_path = tmp_path / 'empty_registry.json'
        result = buffer_utils.find_buffer_dir(str(tmp_path), registry_path=str(reg_path))
        assert result is None

    def test_registry_path_not_on_disk_returns_none(self, tmp_path):
        """Registry points to a buffer_path that doesn't exist."""
        reg_path = tmp_path / 'registry.json'
        self._make_registry(reg_path, {
            'myproj': {
                'repo_root': str(tmp_path / 'ghost'),
                'buffer_path': str(tmp_path / 'ghost' / '.claude' / 'buffer'),
            }
        })
        result = buffer_utils.find_buffer_dir(str(tmp_path / 'ghost'), registry_path=str(reg_path))
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py::TestFindBufferDir -v`
Expected: FAIL

- [ ] **Step 3: Implement `find_buffer_dir`**

Add to `plugin/scripts/buffer_utils.py`:

```python
def find_buffer_dir(cwd, registry_path=None):
    """Find the buffer directory for the given working directory.

    Two-tier lookup:
    1. Registry lookup: check projects.json for a project whose repo_root
       contains cwd. If match found and buffer_path exists on disk, return it.
    2. Walk-up fallback: walk up from cwd looking for .claude/buffer/handoff.json,
       but ONLY accept if the containing directory is a git repo (.git exists).

    Returns absolute path to buffer dir, or None.
    """
    if registry_path is None:
        registry_path = REGISTRY_PATH

    # Tier 1: Registry lookup
    registry = read_registry(registry_path)
    for _name, proj in registry.get('projects', {}).items():
        repo_root = proj.get('repo_root', '')
        buffer_path = proj.get('buffer_path', '')
        if repo_root and match_cwd_to_project(cwd, repo_root):
            if os.path.isdir(buffer_path) and os.path.isfile(
                    os.path.join(buffer_path, 'handoff.json')):
                return buffer_path

    # Tier 2: Walk-up with git guard
    current = os.path.abspath(cwd)
    while True:
        candidate = os.path.join(current, '.claude', 'buffer', 'handoff.json')
        if os.path.exists(candidate):
            # Git guard: only accept if this directory is a git repo
            if is_git_repo(current):
                return os.path.join(current, '.claude', 'buffer')
            # Buffer found but not in a git repo — skip it
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py::TestFindBufferDir -v`
Expected: 6 PASSED

- [ ] **Step 5: Run full test_buffer_utils.py**

Run: `cd session-buffer && python -m pytest tests/test_buffer_utils.py -v`
Expected: ALL PASSED (3 + 5/6 + 5 + 6 = 19-20 tests)

- [ ] **Step 6: Commit**

```bash
cd session-buffer
git add plugin/scripts/buffer_utils.py tests/test_buffer_utils.py
git commit -m "feat: add find_buffer_dir with registry + git-guarded walk-up"
```

---

## Chunk 2: Hook Integration + Existing Test Updates

### Task 5: Replace `find_buffer_dir` in sigma_hook.py

**Files:**
- Modify: `plugin/scripts/sigma_hook.py` (lines 169-179)

- [ ] **Step 1: Replace the function**

In `sigma_hook.py`, replace the `find_buffer_dir` function (lines 169-179) with an import from `buffer_utils`:

```python
# ---------------------------------------------------------------------------
# Buffer discovery — delegated to shared buffer_utils module
# ---------------------------------------------------------------------------

def find_buffer_dir(start_path):
    """Find buffer dir via registry lookup + git-guarded walk-up.

    Delegates to buffer_utils.find_buffer_dir. See buffer_utils.py for details.
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'buffer_utils', os.path.join(script_dir, 'buffer_utils.py'))
        utils = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(utils)
        return utils.find_buffer_dir(start_path)
    except Exception:
        # Fallback: original walk-up (no git guard) if buffer_utils fails
        current = os.path.abspath(start_path)
        while True:
            candidate = os.path.join(current, '.claude', 'buffer', 'handoff.json')
            if os.path.exists(candidate):
                return os.path.join(current, '.claude', 'buffer')
            parent = os.path.dirname(current)
            if parent == current:
                return None
            current = parent
```

- [ ] **Step 2: Run existing sigma_hook tests**

Run: `cd session-buffer && python -m pytest tests/test_sigma_hook.py tests/test_sigma_hook_e2e.py -v`
Expected: ALL PASS (existing behavior preserved via wrapper + fallback)

- [ ] **Step 3: Commit**

```bash
cd session-buffer
git add plugin/scripts/sigma_hook.py
git commit -m "refactor: sigma_hook uses buffer_utils for discovery"
```

---

### Task 6: Replace `find_buffer_dir` in compact_hook.py

**Files:**
- Modify: `plugin/scripts/compact_hook.py` (lines 32-42)

- [ ] **Step 1: Replace the function**

In `compact_hook.py`, replace the `find_buffer_dir` function (lines 32-42) with the same import-delegation pattern:

```python
def find_buffer_dir(start_path):
    """Find buffer dir via registry lookup + git-guarded walk-up.

    Delegates to buffer_utils.find_buffer_dir. See buffer_utils.py for details.
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'buffer_utils', os.path.join(script_dir, 'buffer_utils.py'))
        utils = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(utils)
        return utils.find_buffer_dir(start_path)
    except Exception:
        # Fallback: original walk-up (no git guard) if buffer_utils fails
        current = os.path.abspath(start_path)
        while True:
            candidate = os.path.join(current, '.claude', 'buffer', 'handoff.json')
            if os.path.exists(candidate):
                return os.path.join(current, '.claude', 'buffer')
            parent = os.path.dirname(current)
            if parent == current:
                return None
            current = parent
```

- [ ] **Step 2: Run existing compact_hook tests**

Run: `cd session-buffer && python -m pytest tests/test_compact_hook.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
cd session-buffer
git add plugin/scripts/compact_hook.py
git commit -m "refactor: compact_hook uses buffer_utils for discovery"
```

---

### Task 7: Update existing tests that create buffers without `.git`

**Files:**
- Modify: `tests/test_compact_hook.py`
- Modify: `tests/test_sigma_hook_e2e.py`

The git guard means tests that set up a buffer in `tmp_path` (which has no `.git`) will still work because:
- The existing tests call functions directly (not via `find_buffer_dir`)
- The e2e tests that DO use `find_buffer_dir` pass the buffer_dir directly or set up cwd inside the buffer dir

Check: do any tests actually rely on `find_buffer_dir` finding a buffer in a non-git directory?

- [ ] **Step 1: Search for tests that call find_buffer_dir**

Run: `cd session-buffer && grep -rn "find_buffer_dir(" tests/`

Pre-audit finding: `test_compact_hook.py` imports `find_buffer_dir` at line 13 but does NOT call it in any test body — all tests call specific functions (`cmd_pre_compact`, `build_compact_summary`, etc.) with explicit `buffer_dir` arguments. `test_sigma_hook_e2e.py` calls functions that internally call `find_buffer_dir` — check if those tests create `.git` dirs.

If any test calls `find_buffer_dir(tmp_path_str)` where `tmp_path` has no `.git`, the git guard will cause it to return `None`. The wrapper's fallback only fires if `buffer_utils.py` itself can't be imported — once imported, the git guard is active.

**Fix pattern**: For any test that needs `find_buffer_dir` to succeed, add `(tmp_path / '.git').mkdir()` in the test fixture or setup. For tests that test `find_buffer_dir` returning `None`, no change needed.

- [ ] **Step 2: Run full test suite**

Run: `cd session-buffer && python -m pytest tests/ -v`
Expected: ALL PASS. If any tests fail due to the git guard, fix them by adding `.git` dirs to their fixtures.

- [ ] **Step 3: Fix any failures and commit**

```bash
cd session-buffer
git add tests/
git commit -m "test: add .git dirs to fixtures for git-guarded discovery"
```

---

## Chunk 3: SKILL.md Updates

### Task 8: Rewrite on/SKILL.md Step 0a-0c

**Files:**
- Modify: `plugin/skills/on/SKILL.md` (lines 48-96)

- [ ] **Step 1: Replace Step 0 section**

Replace lines 48-96 (from `## Step 0: Project Routing` through the end of `### 0c: Project selector`) with:

````markdown
## Step 0: Project Routing

**⚠ MANDATORY POPUP**: Always show the project selector via AskUserQuestion before loading anything.
Never auto-load a trunk without user confirmation.

### 0a: Locate project context

Determine what projects are available. Do NOT load any trunk data at this point.

1. Try `git rev-parse --show-toplevel` from the current working directory.
   - **If success**: cwd is inside a git repo. Note the repo root. Check if
     `<repo-root>/.claude/buffer/handoff.json` exists — if so, this is a
     local project with a buffer.

2. **If cwd is NOT a git repo** (git rev-parse fails):
   - Scan **immediate children** of cwd (one level deep only) for directories
     containing `.git/`.
   - For each git-repo child, compute a score:
     | Signal | Score |
     |--------|-------|
     | Has `.claude/buffer/handoff.json` | +1.0 |
     | Has `.git/` | +0.5 |
     | Matches a `projects.json` entry | +0.3 |
   - Sort by score descending.

3. Also read `~/.claude/buffer/projects.json` (if it exists) for entries whose
   `repo_root` is under the current cwd. Merge with filesystem results from
   step 2, deduplicate by repo root path.

### 0b: Project selector (ALWAYS shown)

**⚠ MANDATORY POPUP**: You MUST call `AskUserQuestion` before proceeding.

The popup adapts to what was found in 0a:

**One result with score >= 1.0:**
- Resume [project name] at [repo path] (Recommended) (last handoff: [date])
- Start new project
- Start lite session

**Multiple results with score >= 1.0:**
- Present as ranked list (score descending), top entry pre-selected
- Start new project
- Start lite session

**Results found but all below 1.0 (git repos without buffers):**
- Initialize buffer in [repo name] (highest-scoring)
- Start new project
- Start lite session

**No results + registry has entries:**
- Resume [most recent project from registry] (last handoff: [date])
- Switch to another project (shows full list)
- Start new project
- Start lite session

**No results + no registry (first run):**
- Proceed directly to first-run setup (0d)

If user selects an existing project: load its buffer_path and proceed to Step 0c.
If user selects "Start new project" or "Start lite session": proceed to 0d.

### 0c: Check for project skill

After the user selects a project, check if the selected repo has
`<repo>/.claude/skills/buffer/on.md`.

- **If it exists**: read that file and follow its instructions instead. Stop
  processing this file.
- **If not**: continue with Step 1 (standard on-hand process).
````

- [ ] **Step 2: Verify the SKILL.md is well-formed**

Read the file and check that section headings flow correctly: Step 0 → 0a → 0b → 0c → 0d (first-run) → 0e (registry) → 0f (MEMORY.md) → Standard On-Hand Process.

- [ ] **Step 3: Commit**

```bash
cd session-buffer
git add plugin/skills/on/SKILL.md
git commit -m "feat: rewrite Step 0 discovery with subdirectory scanning"
```

---

### Task 9: Update on/SKILL.md Step 0d and 0e for v2 schema

**Files:**
- Modify: `plugin/skills/on/SKILL.md` (lines 98-146)

- [ ] **Step 1: Update Step 0d (first-run setup)**

In Step 0d, replace item 4 ("Initialize `.claude/buffer/`") with:

```markdown
4. Initialize `.claude/buffer/` with scope-appropriate schemas:
   - **Target directory**: If a git repo was found (via Step 0a), create the
     buffer inside the git repo's `.claude/buffer/`, even if cwd is a parent
     directory. If no git repo was found, create in cwd (lite users without git).
   - **Lite**: `buffer_mode`, `session_meta`, `active_work`, `open_threads`,
     `recent_decisions`, `instance_notes`, `natural_summary`
   - **Full**: Full schema including `concept_map_digest`
```

- [ ] **Step 2: Update Step 0e (registry)**

Replace the entire Step 0e section (v1 schema block + surrounding text) with:

````markdown
### 0e: Register in global project registry

Read (or create) `~/.claude/buffer/projects.json`:

```json
{
  "schema_version": 2,
  "projects": {
    "[project-name]": {
      "repo_root": "[absolute path to git repo root, from git rev-parse --show-toplevel]",
      "buffer_path": "[repo_root]/.claude/buffer",
      "scope": "full | lite",
      "last_handoff": "YYYY-MM-DD",
      "project_context": "[one-sentence description]"
    }
  }
}
```

For lite users without a git repo, `repo_root` equals the working directory.
Add the current project if not already registered. Write back.
````

- [ ] **Step 3: Commit**

```bash
cd session-buffer
git add plugin/skills/on/SKILL.md
git commit -m "feat: Step 0d targets git repo, Step 0e uses v2 schema"
```

---

### Task 10: Update off/SKILL.md Step 12

**Files:**
- Modify: `plugin/skills/off/SKILL.md` (lines 323-342)

- [ ] **Step 1: Replace Step 12 schema**

Replace the v1 schema block (lines 327-337) with v2:

```json
{
  "schema_version": 2,
  "projects": {
    "[project-name]": {
      "repo_root": "[git rev-parse --show-toplevel output]",
      "buffer_path": "[repo_root]/.claude/buffer",
      "scope": "full | lite",
      "last_handoff": "YYYY-MM-DD",
      "project_context": "[one-sentence from orientation.core_insight]"
    }
  }
}
```

Update the text after the schema block to mention: "Use `git rev-parse --show-toplevel` to get the `repo_root` dynamically. If already registered, update `last_handoff` and ensure `repo_root` is present."

- [ ] **Step 2: Commit**

```bash
cd session-buffer
git add plugin/skills/off/SKILL.md
git commit -m "feat: off/SKILL.md Step 12 uses v2 registry schema"
```

---

### Task 11: Run full test suite

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `cd session-buffer && python -m pytest tests/ -v`
Expected: ALL PASS. Run `python -m pytest tests/ --collect-only -q | tail -1` first to get the baseline count, then verify the post-implementation count is baseline + ~20 (new buffer_utils tests).

- [ ] **Step 2: Verify no regressions**

Check that the test count increased (new tests added) and no existing tests broke.

---

## Chunk 4: sigma-TAP Migration (One-Time)

### Task 12: Migrate buffer files to sigma-TAP-repo

**Files:**
- Source: `New folder/.claude/buffer/`
- Target: `sigma-TAP-repo/.claude/buffer/`

- [ ] **Step 1: Copy current-state files (overwrite stale)**

```bash
cd "/c/Users/user/Documents/New folder"
cp .claude/buffer/handoff.json sigma-TAP-repo/.claude/buffer/handoff.json
cp .claude/buffer/handoff-warm.json sigma-TAP-repo/.claude/buffer/handoff-warm.json
cp .claude/buffer/handoff-cold.json sigma-TAP-repo/.claude/buffer/handoff-cold.json
cp .claude/buffer/briefing.md sigma-TAP-repo/.claude/buffer/briefing.md
cp .claude/buffer/compact-directives.md sigma-TAP-repo/.claude/buffer/compact-directives.md
cp .claude/buffer/_changes.json sigma-TAP-repo/.claude/buffer/_changes.json 2>/dev/null || true
cp .claude/buffer/handoff-v1-archive.json sigma-TAP-repo/.claude/buffer/handoff-v1-archive.json 2>/dev/null || true
```

Do NOT copy `.buffer_loaded` (ephemeral session marker).

- [ ] **Step 2: Copy alpha directory tree**

```bash
cp -r .claude/buffer/alpha/* sigma-TAP-repo/.claude/buffer/alpha/
```

- [ ] **Step 3: Copy auxiliary files (take newer)**

```bash
for f in .buffer_trajectory .cw_adjacency .resolution_queue .sigma_hits relevance_grid.json; do
  cp ".claude/buffer/$f" "sigma-TAP-repo/.claude/buffer/$f" 2>/dev/null || true
done
```

- [ ] **Step 4: Move CLAUDE.md**

Check if `sigma-TAP-repo/CLAUDE.md` exists. If not, move directly:
```bash
mv CLAUDE.md sigma-TAP-repo/CLAUDE.md
```
If it exists, merge the `## Compaction Guidance` section into it.

- [ ] **Step 5: Verify target buffer is current**

```bash
cd sigma-TAP-repo
python3 -c "import json; h=json.load(open('.claude/buffer/handoff.json')); print('Phase:', h['active_work']['current_phase'])"
```
Expected: "Phase: Layer 1 compaction directives — implemented, awaiting first live test"

- [ ] **Step 6: Commit in sigma-TAP-repo**

```bash
cd sigma-TAP-repo
git add .claude/buffer/ CLAUDE.md
git commit -m "migrate: buffer from parent workspace to project repo

Buffer was accidentally created in the non-git parent directory (New folder/).
Moved to project repo where plugin users' buffers are expected to live."
```

---

### Task 13: Update projects.json and clean up

**Files:**
- Modify: `~/.claude/buffer/projects.json`
- Remove: `New folder/.claude/buffer/` directory
- Remove: `New folder/CLAUDE.md`

- [ ] **Step 1: Update projects.json to v2**

Write the updated registry:
```json
{
  "schema_version": 2,
  "projects": {
    "sigma-TAP": {
      "repo_root": "C:/Users/user/Documents/New folder/sigma-TAP-repo",
      "buffer_path": "C:/Users/user/Documents/New folder/sigma-TAP-repo/.claude/buffer",
      "scope": "full",
      "last_handoff": "2026-03-14",
      "project_context": "sigma-TAP models PRAXIS via the L-matrix...",
      "remote_backup": false
    }
  }
}
```

- [ ] **Step 2: Remove old buffer directory**

```bash
cd "/c/Users/user/Documents/New folder"
rm -rf .claude/buffer/
```

- [ ] **Step 3: Remove old CLAUDE.md (if still present)**

```bash
rm -f "/c/Users/user/Documents/New folder/CLAUDE.md"
```

- [ ] **Step 4: Post-migration verification**

```bash
# projects.json points to sigma-TAP-repo
cat ~/.claude/buffer/projects.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['projects']['sigma-TAP']['buffer_path'])"
# Expected: C:/Users/user/Documents/New folder/sigma-TAP-repo/.claude/buffer

# Buffer has current phase
cd "/c/Users/user/Documents/New folder/sigma-TAP-repo"
python3 -c "import json; h=json.load(open('.claude/buffer/handoff.json')); print(h['active_work']['current_phase'])"
# Expected: Layer 1 compaction directives — implemented, awaiting first live test

# Old buffer removed
ls "/c/Users/user/Documents/New folder/.claude/buffer/" 2>&1
# Expected: No such file or directory

# No CLAUDE.md in parent
ls "/c/Users/user/Documents/New folder/CLAUDE.md" 2>&1
# Expected: No such file or directory
```

---

### Task 14: Final verification — full test suite + plugin smoke test

- [ ] **Step 1: Run all tests from session-buffer repo**

Run: `cd session-buffer && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Commit plan document**

```bash
cd session-buffer
git add docs/superpowers/plans/2026-03-14-registry-discovery-migration.md
git commit -m "docs: implementation plan for registry discovery + migration"
```
