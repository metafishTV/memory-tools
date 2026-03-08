# distill

Source distillation pipeline for Claude Code. Extracts structured reference knowledge from PDFs, web pages, images, and recordings.

## Install

```
/plugin install distill@memory-tools-by-metafish
```

Companion to the `buffer` plugin. Distill produces reference knowledge; buffer stores and serves it.

## How it works

Run `/distill` with a source document. The pipeline has four stages:

1. **Differentiate** (first run only) -- one-time project setup. Audits your tooling, asks about your project, generates a project-level distill config.
2. **Extract** -- pulls raw content from the source (PDF, image, web page, audio transcript).
3. **Analyze** -- runs analytic passes over the extracted content. Produces structured output with cross-references, concept mappings, and interpretive notes.
4. **Integrate** -- writes results into the buffer's alpha bin (if buffer plugin is installed) or outputs standalone files.

## Quick start

```
/distill path/to/document.pdf
```

First time in a new project, the dispatcher detects no project config and runs differentiation automatically. After that, it goes straight to the extract-analyze-integrate pipeline.

## Output locations

Output paths are configured per-project during the **differentiate** step. Typical layout:

```
<project>/
├── docs/references/
│   ├── INDEX.md                              Master index of all distilled sources
│   ├── distilled/
│   │   ├── AuthorName_Title_Year_Type.md     Structured distillation
│   │   └── figures/
│   │       └── AuthorName_Title/             Extracted figures per source
│   └── interpretations/
│       └── AuthorName_Title_Year_Type.md     Project-specific interpretation
└── .claude/
    ├── buffer/alpha/                          Alpha bin (if buffer plugin installed)
    │   ├── index.json                         Lightweight index
    │   └── <source-folder>/w###.md            Self-contained knowledge atoms
    └── skills/distill/
        ├── SKILL.md                           Project distill config
        └── README.md                          Sources table, glossary, known issues
```

The project-level `README.md` inside `.claude/skills/distill/` tracks all distilled sources, output paths, tooling, and known issues. Check there for the authoritative path table for your project.

## Standalone mode

If the buffer plugin is not installed, distill works standalone -- it produces output files without alpha bin integration. Install buffer to get persistent reference memory with query-on-demand access.

## Requires

Python 3.10+ on PATH. PDF extraction may need `pdftotext` or similar tools (the differentiate step checks your tooling and adapts).

## License

MIT
