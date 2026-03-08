# buffer

Three-layer session memory for Claude Code. Preserves decisions, open threads, concept maps, and working context across sessions.

## Install

```
/plugin marketplace add metafishTV/memory-tools
/plugin install buffer@memory-tools-by-metafish
```

Or add via the Claude app using the git URL: `https://github.com/metafishTV/memory-tools.git`

## How it works

The **sigma trunk** holds your accumulated project knowledge in three layers plus an optional reference layer:

| Layer | File | Default Max | Loaded | Content |
|-------|------|-------------|--------|---------|
| **Hot** | `handoff.json` | 200 lines | Always | Session state, digests, pointers |
| **Warm** | `handoff-warm.json` | 500 lines | Selectively (via pointers) | Decisions archive, concept maps |
| **Cold** | `handoff-cold.json` | 500 lines | On-demand | Historical record |
| **Alpha** | `alpha/index.json` + `.md` files | No cap | Index always, files on-demand | Reference memory (concept maps, convergence webs) |
| **Tower** | `handoff-tower-NNN-*.json` | Sealed | Never | Historical archive |

Each session, you compute the **alpha stash** (what's new since the last handoff) and merge it into the trunk. Content migrates downward (hot -> warm -> cold -> tower) when size bounds are exceeded. Reference material lives in the alpha bin permanently -- no decay, no migration.

## Quick start

**End of session:**
```
/buffer:off
```
Choose your handoff mode:
- **Totalize** -- Complete handoff (concept maps, consolidation, full commit)
- **Quicksave** -- Fast checkpoint (~3 tool calls)
- **Targeted** -- Save specific items you name

**Start of session:**
```
/buffer:on
```
Select your project from the list. Context reconstructed automatically.

## Scope: Full vs Lite

First time you run `/buffer:off`, you choose your scope:

| | Full | Lite |
|---|---|---|
| Decisions, threads, instance notes | yes | yes |
| Concept maps, convergence webs | yes | no |
| Alpha bin (reference memory) | yes | no |
| Conservation (hot -> warm -> cold) | yes | no |
| Tower archival | yes | no |
| MEMORY.md sync | yes | optional |

Upgrade from Lite to Full anytime. No data loss.

## Alpha bin (reference memory)

The alpha bin separates **reference memory** (static, query-on-demand, no decay) from **working memory** (dynamic, session-facing, bounded). It stores concept map entries and convergence web linkages as individual `.md` files under `alpha/`, addressable by ID via a lightweight index.

Alpha is created automatically when you first run a distillation (via the companion `distill` plugin). Without alpha, the buffer operates on hot/warm/cold only -- all alpha wiring stays silent.

Each entry is a **self-contained knowledge atom** (~30 lines) with Definition, Significance, Project Mapping, Related cross-references, and Source citation. A `<!-- TERMINAL -->` directive prevents AI from following reference chains back to full distillation files -- the alpha entry IS the canonical read.

**Commands:**
- `alpha-read` -- summary of what's in the alpha bin
- `alpha-query --id w:218` -- retrieve a specific referent
- `alpha-query --source sartre` -- list entries from a source
- `alpha-query --concept totalization` -- search by concept
- `alpha-write` -- write new entries (JSON on stdin or `--input file.json`)
- `alpha-enrich` -- enrich existing entries with rich body content (preserves header, replaces body)
- `alpha-delete --id w:218` -- remove entries
- `alpha-validate` -- check index integrity

## Companion: distill plugin

The `distill` plugin is the production half of the memory system. Buffer stores and serves; distill produces.

```
/plugin install distill@memory-tools-by-metafish
```

Distill extracts structured reference knowledge from PDFs, web pages, images, and recordings, then writes it into the alpha bin via `alpha-write`. The two plugins interlock automatically -- no manual wiring needed.

## Compact hooks

Includes automatic context preservation:
- **PreCompact** -- saves hot-layer state and writes a `.compact_marker` before compaction
- **Post-compaction relay** -- on next user prompt, detects the marker, injects full buffer recovery into context, then erases the marker

This closes the mid-session compaction gap: even if Claude Code compacts your conversation, your buffer state is restored automatically.

## Per-project configuration

Create `.claude/buffer.local.md` in your project root to customize buffer behavior:

```markdown
---
hot_max: 250
warm_max: 800
cold_max: 750
---
```

Layer limits override the defaults (200/500/500). The buffer manager reads these automatically.

## Remote backup

First-run setup offers to connect a GitHub repo for automatic backup on every handoff.

## Requires

Python 3.10+ on PATH (`python3` or `python`). Scripts use stdlib only -- no pip installs.

## License

MIT
