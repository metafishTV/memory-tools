# Distill Companion Plugin Design

**Date**: 2026-03-07
**Status**: Approved

## Context

The buffer plugin (`session-buffer`) provides three-layer session memory (hot/warm/cold) with an alpha bin for crystallized reference knowledge. The alpha bin has full read/write/delete infrastructure in `buffer_manager.py` and live matching in `sigma_hook.py`, but the only way to *produce* alpha content is via the distill skill — a monolithic ~1400-line skill that exceeds Claude Code's 25K token read limit.

The distill skill also carries sigma-TAP-specific terminology throughout, limiting reuse across projects.

## Architecture: Yin & Yang

Two plugins that interlock:

| Plugin | Role | Contains |
|--------|------|----------|
| **buffer** (yin) | Operational memory | Hot/warm/cold layers, sigma hook, alpha bin infrastructure (read/write/delete/query/validate), on/off skills |
| **distill** (yang) | Knowledge production | Source distillation pipeline, differentiation, extraction, analysis, integration |

**Interlock mechanism**: The buffer plugin keeps all alpha wiring behind `if os.path.isdir(alpha_dir)` guards. Installing the distill plugin and running a first distillation creates `alpha/` via `alpha-write`, and the buffer plugin's existing machinery lights up automatically. Without the distill plugin, the buffer works normally — just without alpha.

The distill plugin checks for the buffer plugin silently. If buffer is present, it writes to alpha via `buffer_manager.py alpha-write`. If not, it produces distilled files standalone.

## Plugin Structure

```
distill/
├── .claude-plugin/
│   └── plugin.json
└── skills/
    ├── distill/
    │   └── SKILL.md              # Dispatcher (~40 lines)
    ├── differentiate/
    │   └── SKILL.md              # One-time project setup (~400 lines)
    ├── extract/
    │   └── SKILL.md              # PDF/image/web extraction pipeline (~300 lines)
    ├── analyze/
    │   └── SKILL.md              # Analytic passes + output template (~400 lines)
    └── integrate/
        └── SKILL.md              # Post-distillation updates (~200 lines)
```

**plugin.json**:
```json
{
  "name": "distill",
  "version": "1.0.0",
  "description": "Source distillation pipeline with reference knowledge extraction. Companion to the buffer plugin.",
  "author": { "name": "metafish", "url": "https://github.com/metafishTV" },
  "repository": "https://github.com/metafishTV/memory-tools",
  "license": "MIT",
  "keywords": ["distill", "extraction", "knowledge", "reference", "alpha"]
}
```

## Invocation Flow

```
User: /distill [path]
  └─ Dispatcher checks for project-level distill config (silently)
     ├─ No config → invoke distill:differentiate first → then extract→analyze→integrate
     └─ Config exists → invoke distill:extract → distill:analyze → distill:integrate
```

Pure Distillation Fast Path: `/distill <path>` with a direct source path skips the greeting and goes straight to extract.

## Sub-Skill Contents

### 1. `distill/SKILL.md` — Dispatcher (~40 lines)

- Check if `.claude/skills/distill/SKILL.md` exists in project (silently)
- If absent → invoke `distill:differentiate`
- If present → route to `distill:extract` (user provides source)
- After extract → `distill:analyze` → `distill:integrate`
- Handle fast path: `/distill <path>` goes straight to extract

### 2. `differentiate/SKILL.md` — One-time Setup (~400 lines)

Generalized from current global skill Steps 0-4b:

- Tooling audit (detect available PDF tools, Python version)
- Project scan (find existing sources, docs structure, framework)
- User questionnaire (project terminology, output preferences, framework vocabulary)
- Generate project-level `distill/SKILL.md` with filled-in glossary and configuration

All sigma-TAP terminology removed. Framework-specific vocabulary lives only in the generated project skill.

### 3. `extract/SKILL.md` — Extraction Pipeline (~300 lines)

Generalized from current skill's extraction sections (already mostly framework-agnostic):

- PDF extraction pipeline (Routes A-G: marker, docling, GROBID, pdftotext, fallbacks)
- Non-PDF handling (web pages, images, plain text)
- Figure handling pipeline (extraction, cropping, naming)
- Demand-install protocol (docling, marker auto-install triggers)
- Source label convention (`Author_Title_Year` pattern)

### 4. `analyze/SKILL.md` — Analytic Passes + Output Template (~400 lines)

Generalized from current skill's analytic and template sections:

- 5-pass analytic structure
- Output template (Core Argument, Key Concepts, Figures, Equations, Implications, Empirical Data)
- Generic project interpretation file template
- Style conventions, voice rules, citation rules
- Alternative templates (fiction, nonfiction, technical)

Project-specific interpretation template moves to the generated project skill.

### 5. `integrate/SKILL.md` — Post-Distillation Updates (~200 lines)

Buffer-aware with silent fallback:

**Full integration mode** (buffer plugin detected):
1. Write `.distill_active` marker (suppress sigma hook)
2. Call `alpha-write` with distilled cross-source entries
3. Update project distill README (sources distilled list)
4. Clean up `.distill_active` marker
5. Run `alpha-validate` for integrity check

**File-only mode** (no buffer plugin):
1. Produce distilled `.md` files in output directory
2. Produce interpretation `.md` files alongside
3. Update project distill README
4. Skip alpha/buffer operations silently

Error logging and temporary file cleanup also live here.

## Buffer Plugin Changes

### sigma_hook.py — Alpha existence guard

```python
# Guard alpha loading behind directory existence
alpha_dir = os.path.join(buffer_dir, 'alpha')
if os.path.isdir(alpha_dir):
    alpha_idx = read_json(os.path.join(alpha_dir, 'index.json'))
    concept_index = alpha_idx.get('concept_index', {}) if alpha_idx else {}
    sources_data = alpha_idx.get('sources', {}) if alpha_idx else {}
else:
    alpha_idx = None
    concept_index = {}
    sources_data = {}
```

When `concept_index` is empty (no alpha), IDF weights default to 1.0 for all keywords. Hot layer matching works normally. Cascade level 2 (alpha matching) returns no hits and emits hot-only results.

### on/SKILL.md — Conditional Step 1b

Step 1b (alpha bin detection) becomes conditional:
- If `alpha/` directory exists → run `alpha-read`, report alpha status
- Otherwise → skip silently, continue to Step 2

### off/SKILL.md — Conditional Steps 6 & 6b

Steps 6 (concept map) and 6b (consolidation) become conditional:
- If `alpha/` directory exists → run concept map workflow with `alpha-write`, consolidation with `alpha-delete`
- Otherwise → skip concept map and consolidation, just write hot/warm/cold layers

### buffer_manager.py — No changes needed

Alpha subcommands already fail gracefully when `alpha/index.json` doesn't exist.

## Generalization Map

| Current (sigma-TAP specific) | Generalized |
|---|---|
| TAPS signatures | framework signatures |
| L-matrix | cross-reference matrix |
| sigma hook | live matching hook |
| metathetic classification | synthesis classification |
| sigma trunk | session buffer |
| alpha stash | reference bin |
| convergence web | convergence network |
| forward notes | research notes |

All project-specific vocabulary lives in the generated project skill's terminology glossary, never in the plugin skills.

## User-Facing Interactions

- **Differentiate** (first run): Interactive questionnaire via `AskUserQuestion`
- **Extract** (every run): User provides source path
- **Analyze** (every run): Automatic, follows project config
- **Integrate** (every run): Automatic, silent buffer detection

No routing popups. No ceremony. The dispatcher handles routing silently.

## Monorepo Placement

The distill plugin lives alongside the buffer plugin in the `memory-tools` repository:

```
memory-tools/
├── session-buffer/          # Buffer plugin (yin)
│   └── plugin/
└── distill/                 # Distill plugin (yang)
    └── plugin/              # or just distill/ at root with .claude-plugin/ inside
```

Both plugins ship from the same repo but install independently.
