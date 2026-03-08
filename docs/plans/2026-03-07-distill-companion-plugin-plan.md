# Distill Companion Plugin — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split the monolithic distill skill into a companion plugin with 4 sub-skills, add alpha existence guards to the buffer plugin, and generalize all sigma-TAP terminology.

**Architecture:** Pure skill plugin (`distill`) alongside the buffer plugin (`session-buffer`) in the memory-tools monorepo. The buffer plugin keeps all alpha wiring behind `if alpha_dir_exists` guards. The distill plugin calls buffer's alpha commands when available, degrades gracefully when not.

**Tech Stack:** Markdown skills (SKILL.md), Python (sigma_hook.py guard), Claude Code plugin framework

**Design doc:** `docs/plans/2026-03-07-distill-companion-plugin-design.md`

---

## Task 1: Buffer Plugin — Add alpha existence guard to sigma_hook.py

**Files:**
- Modify: `plugin/scripts/sigma_hook.py:579-583` (alpha loading block)
- Modify: `plugin/scripts/sigma_hook.py:612-613` (Level 2 empty check)

**Step 1: Add alpha directory existence guard**

In `sigma_hook.py`, replace lines 579-583:

```python
    # Load alpha index once (needed for IDF computation + Level 2 matching)
    alpha_path = os.path.join(buffer_dir, 'alpha', 'index.json')
    alpha_idx = read_json(alpha_path)
    concept_index = alpha_idx.get('concept_index', {}) if alpha_idx else {}
    sources_data = alpha_idx.get('sources', {}) if alpha_idx else {}
```

With:

```python
    # Load alpha index if alpha bin exists (needed for IDF computation + Level 2 matching)
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

**Step 2: Test — alpha bin absent**

Create a test buffer directory with NO `alpha/` directory. Verify sigma hook runs cleanly with hot-layer-only matching:

```bash
TMPDIR=$(mktemp -d)
mkdir -p "$TMPDIR/buffer"
echo '{"changes":{"test_concept":{"decision":"keep"}}}' > "$TMPDIR/buffer/handoff.json"
echo '{"user_prompt":"Tell me about test concept"}' | python plugin/scripts/sigma_hook.py 2>/dev/null
# Expected: hot-layer hit OR empty JSON (no crash, no alpha error)
```

**Step 3: Test — alpha bin present**

Use the existing sigma-TAP buffer directory which has `alpha/`:

```bash
echo '{"user_prompt":"Tell me about alterity and rhizomatic processes"}' | BUFFER_DIR=<path-with-alpha> python plugin/scripts/sigma_hook.py
# Expected: alpha concept matches (same behavior as before)
```

**Step 4: Commit**

```bash
git add plugin/scripts/sigma_hook.py
git commit -m "feat: guard alpha loading behind directory existence check

sigma_hook.py now gracefully degrades when alpha bin is absent.
IDF weights default to 1.0, hot layer works normally, cascade level 2
returns no hits. Enables buffer plugin to work without distill companion."
```

---

## Task 2: Buffer Plugin — Add alpha guards to on/off skills

**Files:**
- Modify: `plugin/skills/on/SKILL.md:196-219` (Step 1b)
- Modify: `plugin/skills/on/SKILL.md:269-270` (Step 4 alpha-query)
- Modify: `plugin/skills/off/SKILL.md:189-209` (Step 6)
- Modify: `plugin/skills/off/SKILL.md:211-248` (Step 6b)

**Step 1: Add conditional gate to on/SKILL.md Step 1b**

Wrap the Step 1b content with a conditional. Before line 200, add:

```markdown
Check if alpha bin directory exists: `ls .claude/buffer/alpha/index.json 2>/dev/null`

**If alpha bin does NOT exist** — skip this step silently, proceed to Step 2.

**If alpha bin exists:**
```

**Step 2: Add conditional to on/SKILL.md Step 4 pointer resolution**

At line 269, change:

```markdown
2. **Check alpha index first** — run `alpha-query --id [id]` to retrieve from alpha bin.
```

To:

```markdown
2. **If alpha bin exists**, check alpha index first — run `alpha-query --id [id]` to retrieve from alpha bin.
```

**Step 3: Add conditional gate to off/SKILL.md Step 6**

Before line 193, add a conditional gate:

```markdown
Check if alpha bin directory exists: `ls .claude/buffer/alpha/index.json 2>/dev/null`

**If alpha bin does NOT exist** — skip this step. Concept map operations are deferred until the distill plugin provisions the alpha bin.

**If alpha bin exists:**
```

**Step 4: Add conditional gate to off/SKILL.md Step 6b**

Before line 215, add:

```markdown
**If alpha bin does NOT exist** — skip this step entirely.
```

**Step 5: Commit**

```bash
git add plugin/skills/on/SKILL.md plugin/skills/off/SKILL.md
git commit -m "feat: conditional alpha gates in on/off skills

Steps that reference alpha bin (1b, 4, 6, 6b) now check for alpha
directory existence first. When alpha is absent, these steps are
skipped silently — buffer works with hot/warm/cold only."
```

---

## Task 3: Create distill plugin scaffold

**Files:**
- Create: `distill/.claude-plugin/plugin.json`
- Create: `distill/skills/distill/SKILL.md` (dispatcher)

**Step 1: Create plugin directory structure**

```bash
cd <repo-root>  # session-buffer's parent: "C:/Users/user/Documents/New folder"
mkdir -p distill/.claude-plugin
mkdir -p distill/skills/distill
mkdir -p distill/skills/differentiate
mkdir -p distill/skills/extract
mkdir -p distill/skills/analyze
mkdir -p distill/skills/integrate
```

**Step 2: Write plugin.json**

Create `distill/.claude-plugin/plugin.json`:

```json
{
  "name": "distill",
  "version": "1.0.0",
  "description": "Source distillation pipeline with reference knowledge extraction. Companion to the buffer plugin — distill produces, buffer stores and serves.",
  "author": { "name": "metafish", "url": "https://github.com/metafishTV" },
  "repository": "https://github.com/metafishTV/memory-tools",
  "license": "MIT",
  "keywords": ["distill", "extraction", "knowledge", "reference", "alpha"]
}
```

**Step 3: Write dispatcher SKILL.md**

Create `distill/skills/distill/SKILL.md` (~40 lines):

```markdown
---
name: distill
description: Distill source documents (PDF, image, web) with project integration. Routes to sub-skills for extraction, analysis, and integration.
---

# Source Distillation

Distill a source document into structured reference knowledge.

## Routing

1. **Check for project config** (silent): look for `.claude/skills/distill/SKILL.md` in the project directory.

2. **If no project config exists**:
   - This is a first-time distillation for this project.
   - Invoke the `distill:differentiate` skill to run one-time setup.
   - After differentiation completes, continue to step 3.

3. **Read the project config**: `.claude/skills/distill/SKILL.md` — this has the project-specific terminology, output paths, and tooling profile.

4. **Run the pipeline** in sequence:
   a. Invoke `distill:extract` — extracts raw content from the source document
   b. Invoke `distill:analyze` — runs analytic passes and produces the distilled output
   c. Invoke `distill:integrate` — updates project indexes, buffer, and reference bin

## Fast Path

If the user provides a source path directly (e.g., `/distill docs/references/Author_Title_2024.pdf`), skip the greeting and go straight to step 3 (or step 2 if no project config).

## Arguments

The source path can be provided as an argument or the user will be asked for it during the extract step.
```

**Step 4: Verify plugin structure**

```bash
find distill/ -type f | sort
# Expected:
# distill/.claude-plugin/plugin.json
# distill/skills/distill/SKILL.md
# distill/skills/differentiate/SKILL.md (placeholder)
# distill/skills/extract/SKILL.md (placeholder)
# distill/skills/analyze/SKILL.md (placeholder)
# distill/skills/integrate/SKILL.md (placeholder)
```

**Step 5: Commit scaffold**

```bash
git add distill/
git commit -m "feat: scaffold distill companion plugin

Plugin manifest, dispatcher skill, and directory structure for 4 sub-skills:
differentiate, extract, analyze, integrate."
```

---

## Task 4: Write differentiate sub-skill

**Files:**
- Create: `distill/skills/differentiate/SKILL.md` (~400 lines)

**Source material:** Global distill SKILL.md lines 92-461 (Steps 0-4b), generalized.

**Step 1: Write the differentiate skill**

Extract and generalize these sections from the global distill SKILL.md:
- Step 0: Check for Project Skill (lines 92-127) → adapt as pre-check
- Step 0a: Pre-Existing Infrastructure Detection (lines 110-126)
- Step 1: Tooling Audit (lines 138-188) → keep as-is (already generic)
- Step 2: Project Scan (lines 190-212) → keep as-is (already generic)
- Step 3: User Questionnaire (lines 214-281) → generalize sigma-TAP references
- Step 4: Generate Project Skill (lines 283-403) → generalize the template
- Step 4b: Generate Project README (lines 405-461) → keep as-is

**Generalization changes:**
- Remove "TAPS" → "framework" or "project" throughout
- Remove "sigma" → "session" or "buffer" throughout
- Remove "L-matrix" → "cross-reference matrix"
- Remove "metathetic" → "synthesis"
- The generated project skill template becomes framework-neutral
- The terminology glossary section becomes empty (user fills it during questionnaire)

**Step 2: Verify line count is under 500**

```bash
wc -l distill/skills/differentiate/SKILL.md
# Target: ~350-400 lines (well under 25K token limit)
```

**Step 3: Commit**

```bash
git add distill/skills/differentiate/SKILL.md
git commit -m "feat: differentiate sub-skill — one-time project setup

Generalized from global distill skill Steps 0-4b. Runs tooling audit,
project scan, user questionnaire, and generates project-level distill
config. All framework-specific vocabulary removed."
```

---

## Task 5: Write extract sub-skill

**Files:**
- Create: `distill/skills/extract/SKILL.md` (~300 lines)

**Source material:** Global distill SKILL.md lines 465-835, generalized.

**Step 1: Write the extract skill**

Extract and generalize these sections:
- Source Label Convention (lines 474-519) → keep as-is (already generic `Author_Title_Year`)
- PDF Extraction Pipeline (lines 544-618) → keep as-is (already generic)
- Non-PDF Source Handling (lines 620-695) → keep as-is
- Route R — Recordings (lines 697-749) → keep as-is
- Figure Handling Pipeline (lines 751-816) → keep as-is
- Demand-Install Protocol (lines 818-835) → keep as-is

**Generalization changes:**
- Remove "sigma hook marker" reference from DISTILLATION MODE header (line 465-473) — that moves to integrate skill
- Remove any sigma-TAP example source labels → use generic examples
- The extraction pipeline is already framework-agnostic

**Step 2: Add project config reference**

At the top, add instruction to read the project distill config for output paths and tooling profile:

```markdown
## Prerequisites

Read the project distill config at `.claude/skills/distill/SKILL.md` for:
- Output directory paths
- Available tooling (marker, docling, GROBID, pdftotext)
- Source label conventions (may be customized)
```

**Step 3: Verify line count**

```bash
wc -l distill/skills/extract/SKILL.md
# Target: ~280-320 lines
```

**Step 4: Commit**

```bash
git add distill/skills/extract/SKILL.md
git commit -m "feat: extract sub-skill — PDF/image/web extraction pipeline

Generalized extraction pipeline with Routes A-G for PDFs, web sources,
images, and recordings. Figure handling, demand-install protocol.
Framework-agnostic — reads project config for paths and tooling."
```

---

## Task 6: Write analyze sub-skill

**Files:**
- Create: `distill/skills/analyze/SKILL.md` (~400 lines)

**Source material:** Global distill SKILL.md lines 521-1088, generalized.

**Step 1: Write the analyze skill**

Extract and generalize these sections:
- Analytic Passes 1-5 (lines 521-543) → keep structure, generalize examples
- Output Template (lines 839-913) → keep as-is (Core Argument, Key Concepts, etc.)
- Style Conventions (lines 915-930) → keep as-is
- Voice Rule (lines 932-950) → keep as-is
- Source Citation Rules (lines 952-983) → keep as-is
- Project Interpretation File templates (lines 985-1088) → generalize
- Troubleshooting Decision Tree (lines 1093-1210) → keep as-is

**Generalization changes:**
- Replace "sigma-TAP Interpretation File" → "Project Interpretation File"
- Remove project-specific interpretation template examples → use generic placeholders
- Keep the 4 template types (concept_convergence, thematic, narrative, custom)
- The troubleshooting tree is already framework-agnostic

**Step 2: Add project config reference**

```markdown
## Prerequisites

Read the project distill config at `.claude/skills/distill/SKILL.md` for:
- Project terminology glossary (domain-specific vocabulary)
- Interpretation template type (concept_convergence, thematic, narrative, custom)
- Output formatting preferences
```

**Step 3: Verify line count**

```bash
wc -l distill/skills/analyze/SKILL.md
# Target: ~380-420 lines
```

**Step 4: Commit**

```bash
git add distill/skills/analyze/SKILL.md
git commit -m "feat: analyze sub-skill — analytic passes and output template

Five-pass analytic structure, output template, style conventions,
interpretation file generation, troubleshooting decision tree.
Framework-agnostic — reads project terminology from generated config."
```

---

## Task 7: Write integrate sub-skill

**Files:**
- Create: `distill/skills/integrate/SKILL.md` (~200 lines)

**Source material:** Global distill SKILL.md lines 1212-1389, generalized.

**Step 1: Write the integrate skill**

Extract and generalize these sections:
- Post-Distillation Updates (lines 1212-1339)
  - INDEX.md Update (lines 1230-1240)
  - Buffer Update (lines 1242-1289)
  - MEMORY.md Update (lines 1291-1299)
  - Convergence Web Update (lines 1301-1338) → generalize to "convergence network"
- Project README Update (lines 1340-1350)
- Error Logging (lines 1352-1365)
- Temporary File Cleanup (lines 1367-1389)

**Step 2: Add buffer plugin detection**

At the top, add silent detection:

```markdown
## Buffer Plugin Detection

Check if the buffer plugin is available:

1. Look for `buffer_manager.py` in the plugin scripts path
2. Check if `.claude/buffer/` directory exists in the project

**If buffer plugin is available** — run full integration mode (alpha writes, sigma hook marker, etc.)

**If buffer plugin is NOT available** — run file-only mode (produce output files, skip alpha/buffer operations silently)
```

**Step 3: Structure the two modes**

```markdown
## Full Integration Mode (buffer plugin detected)

1. Write `.distill_active` marker: `echo "active" > .claude/buffer/.distill_active`
2. Compute cross-source entries from the distilled output
3. Write entries to alpha bin:
   ```bash
   echo '<json>' | buffer_manager.py alpha-write --buffer-dir .claude/buffer/
   ```
4. Update INDEX.md with new source entry
5. Update MEMORY.md with source summary
6. Update convergence network entries (if applicable)
7. Update project README with new source
8. Remove `.distill_active` marker: `rm -f .claude/buffer/.distill_active`
9. Run integrity check: `buffer_manager.py alpha-validate --buffer-dir .claude/buffer/`

## File-Only Mode (no buffer plugin)

1. Produce distilled `.md` file in output directory
2. Produce interpretation `.md` file alongside
3. Update INDEX.md with new source entry
4. Update project README with new source

## Cleanup (both modes)

- Remove temporary files: `_distill_scan.json`, `_distill_text.txt`, `_manifest.json`
- If buffer exists: `rm -f .claude/buffer/.distill_active`

## Error Logging (mandatory)

[Error log format from global skill lines 1352-1365]
```

**Step 4: Verify line count**

```bash
wc -l distill/skills/integrate/SKILL.md
# Target: ~180-220 lines
```

**Step 5: Commit**

```bash
git add distill/skills/integrate/SKILL.md
git commit -m "feat: integrate sub-skill — post-distillation updates

Buffer-aware integration with silent fallback. Full mode: alpha-write,
sigma hook marker, convergence network. File-only mode: output files
and index updates only. Error logging and cleanup."
```

---

## Task 8: Retire global distill skill

**Files:**
- Modify: `~/.claude/skills/distill/SKILL.md` (replace with pointer to plugin)

**Step 1: Replace global skill with redirect**

Replace the entire 1389-line global skill with a short redirect:

```markdown
---
name: distill
description: Distill source documents (PDF, image, web) with project integration. Differentiates on first run per project.
---

# Source Distillation

This skill has been moved to the **distill plugin**.

Install the distill plugin from the memory-tools repository, then use `/distill` to invoke it.

The distill plugin provides 4 sub-skills:
- `distill:differentiate` — one-time project setup
- `distill:extract` — PDF/image/web extraction pipeline
- `distill:analyze` — analytic passes and output template
- `distill:integrate` — post-distillation buffer and index updates
```

**Step 2: Verify the plugin distill skill takes priority**

When both the global skill and the plugin skill exist, the plugin skill should take priority via the namespace `distill:distill`. Verify by checking that `/distill` invokes the plugin dispatcher, not the global redirect.

**Step 3: Commit**

```bash
git add ~/.claude/skills/distill/SKILL.md
# Note: this is a user-global file, not in the repo. No git commit needed.
# Just ensure the file is updated locally.
```

---

## Task 9: Update sigma-TAP project distill skill

**Files:**
- Modify: `sigma-TAP-repo/.claude/skills/distill/SKILL.md` (add plugin reference)

**Step 1: Add plugin awareness**

Add a note at the top of the project distill skill that it was generated by the distill plugin's differentiate skill, and that the plugin's extract/analyze/integrate skills should be used for the pipeline:

```markdown
> **Generated by:** distill:differentiate plugin skill
> **Pipeline:** distill:extract → distill:analyze → distill:integrate
```

The project skill's content (configuration, tooling profile, terminology glossary, known issues) remains unchanged — it's the project-specific config that the sub-skills read.

**Step 2: Commit to sigma-TAP repo**

```bash
cd sigma-TAP-repo
git add .claude/skills/distill/SKILL.md
git commit -m "chore: add distill plugin reference to project distill config"
```

---

## Task 10: Final validation and push

**Step 1: Verify plugin structure**

```bash
find distill/ -name "*.md" -o -name "*.json" | sort
```

Expected:
```
distill/.claude-plugin/plugin.json
distill/skills/analyze/SKILL.md
distill/skills/differentiate/SKILL.md
distill/skills/distill/SKILL.md
distill/skills/extract/SKILL.md
distill/skills/integrate/SKILL.md
```

**Step 2: Verify all sub-skills are under 500 lines**

```bash
wc -l distill/skills/*/SKILL.md
```

**Step 3: Verify sigma_hook.py still works with alpha**

```bash
echo '{"user_prompt":"Tell me about alterity"}' | python plugin/scripts/sigma_hook.py
# Should still produce alpha matches when alpha/ exists
```

**Step 4: Verify sigma_hook.py works without alpha**

```bash
# Test with a buffer dir that has no alpha/ directory
echo '{"user_prompt":"Tell me about alterity"}' | BUFFER_DIR=/tmp/no-alpha python plugin/scripts/sigma_hook.py
# Should produce empty JSON or hot-only results (no crash)
```

**Step 5: Push everything**

```bash
# Push session-buffer (buffer plugin changes + distill plugin)
cd session-buffer
git push origin master

# Push sigma-TAP
cd sigma-TAP-repo
git push origin main
```

---

## Summary

| Task | What | Est. lines changed |
|------|------|-------------------|
| 1 | sigma_hook.py alpha guard | ~10 lines |
| 2 | on/off skill alpha guards | ~20 lines |
| 3 | Distill plugin scaffold + dispatcher | ~50 lines |
| 4 | Differentiate sub-skill | ~400 lines |
| 5 | Extract sub-skill | ~300 lines |
| 6 | Analyze sub-skill | ~400 lines |
| 7 | Integrate sub-skill | ~200 lines |
| 8 | Retire global distill skill | ~15 lines (replacement) |
| 9 | Update project distill skill | ~5 lines |
| 10 | Validation and push | 0 lines |

**Total new content:** ~1,400 lines across 5 skill files + ~30 lines of code changes
**Commit cadence:** One commit per task (10 commits total)
