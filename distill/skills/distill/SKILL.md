---
name: distill
description: Distill source documents (PDF, image, web) with project integration. Routes to sub-skills for extraction, analysis, and integration.
---

# Source Distillation

**ENFORCEMENT RULE — applies to all sub-skills invoked below.**

Sub-skills use two interaction levels:

| Marker | When | How |
|--------|------|-----|
| **⚠ MANDATORY POPUP** | Quick binary/ternary decisions (source label, install offer, proceed/stop) | `AskUserQuestion` with 2-3 short options |
| **⚠ MANDATORY REVIEW** | Dense information the user needs to read (scan summary, interpretation review, integration results) | Print information as **plain text** first, then `AskUserQuestion` with brief decision options only. The popup is the decision; the information is the plain text above it. |

**⚠ FULL STOP protocol — applies to BOTH levels:**

After calling `AskUserQuestion`, you MUST stop generating. Do not continue to the next step. Do not prefetch, prepare, or begin any subsequent work. Do not write "while we wait" or "in the meantime." Your turn ENDS with the `AskUserQuestion` call. The next step begins ONLY in your next turn, AFTER the user has responded. This is a hard gate, not a courtesy pause. If you catch yourself writing anything after the `AskUserQuestion` call, STOP IMMEDIATELY.

Distill a source document into structured reference knowledge.

## Project Discovery

Before routing, resolve the **project root** — the directory containing `.claude/skills/distill/SKILL.md`. Search in this order (stop at first hit):

1. **CWD**: check `[CWD]/.claude/skills/distill/SKILL.md`
2. **Git root**: run `git rev-parse --show-toplevel 2>/dev/null` — if it returns a directory different from CWD, check there
3. **Sibling directories**: check `[CWD]/*/. claude/skills/distill/SKILL.md` (one level deep — catches `repo-name/` sitting next to CWD)
4. **Parent directory**: check `[CWD]/../.claude/skills/distill/SKILL.md`

If found, set `project_root` to the directory containing `.claude/`. All subsequent path resolution (distillation_dir, figures_dir, etc.) is relative to `project_root`, NOT CWD.

If not found in any location, this is a first-time project — proceed to step 2.

## Routing

1. **Check for project config** (silent): use the Project Discovery path above to locate `.claude/skills/distill/SKILL.md`.

2. **If no project config exists**:
   - This is a first-time distillation for this project.
   - Invoke the `distill:differentiate` skill to run one-time setup.
   - After differentiation completes, continue to step 3.

3. **Read the project config ONCE**: `.claude/skills/distill/SKILL.md` — this has the project-specific terminology, output paths, and tooling profile. Extract and hold in working context:
   - `project_name`, `project_map_type`, `pure_mode`
   - `distillation_dir`, `figures_dir`, `interpretations_dir`
   - `terminology_glossary` (for Pass 4 mappings)
   - `tooling_profile` (installed/demand-install/never per tool)
   - `memory_config`, `custom_schema` (if applicable)

   **Context passing**: Each sub-skill's "Read project config" step becomes a **verification check** — confirm the config values are already loaded in the conversation context from this step, rather than re-reading the file. The parent skill reads once; the sub-skills use the loaded context. This eliminates redundant file reads per distillation.

   **Template-first principle**: Sub-skills provide inline templates for all output formats (interpretation files, INDEX.md rows, alpha-write JSON, README rows, Known Issues rows). Use the inline template directly — do NOT read existing output files to learn the pattern. Only read existing files when you need to UPDATE them (e.g., adding a row to an existing INDEX.md). For creation, the template IS the pattern.

4. **Run the pipeline** in sequence, passing config context forward:
   a. Invoke `distill:extract` — extracts raw content from the source document
   b. Invoke `distill:analyze` — runs analytic passes and produces the distilled output
   c. Invoke `distill:integrate` — updates project indexes, buffer, and reference bin

## Fast Path

If the user provides a source path directly (e.g., `/distill docs/references/Author_Title_2024.pdf`), skip the greeting and go straight to step 3 (or step 2 if no project config).

## Multi-Source Handling

If the user provides **multiple sources** (multiple URLs, files, or a mix):

**⚠ MANDATORY POPUP**: Present via `AskUserQuestion`:

- **"Series / sequence"** — These are parts of a whole (lecture series, book chapters, essay sequence). Process in order. Later items may reference earlier ones. Use a parent label (e.g., `Author_SeriesName_Year`) with part suffixes (`_Part01`, `_Part02`). Single compound INDEX.md entry.
- **"Independent items (batch)"** — Unrelated sources. Process each independently with its own label, distillation, and INDEX.md entry.

**⚠ FULL STOP** — see ENFORCEMENT RULE. Wait for user response.

For **series**: also ask whether the user wants:
- Combined transcript/text (single `.md` with part headings) — better for tracing cross-part arguments
- Separate files per part (individual `.md` files) — better for targeted retrieval

For **independent batch**: process each source through the full pipeline sequentially. No cross-referencing between items.

## Arguments

The source path can be provided as an argument or the user will be asked for it during the extract step.
