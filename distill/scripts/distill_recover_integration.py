#!/usr/bin/env python3
"""distill_recover_integration.py — Recover orphaned distillations into alpha bin.

Scans interpretation files for structured concept mappings, cross-source
connections, and forward note candidates. Cross-references against
alpha/index.json to find sources with no entries. Generates alpha-write
compatible JSON for the missing data.

Usage:
    python distill_recover_integration.py \
        --interp-dir docs/references/interpretations \
        --distill-dir docs/references/distilled \
        --alpha-dir .claude/buffer/alpha \
        --output recovery.json \
        [--forward-notes-out forward_notes.json] \
        [--dry-run]

Output JSON is an array suitable for piping to:
    cat recovery.json | buffer_manager.py alpha-write --buffer-dir ...

Dependencies: Python 3.10+ (stdlib only)
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from datetime import date, datetime, timezone

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Concept key normalization (from distill_backfill_alpha.py)
# ---------------------------------------------------------------------------

def normalize_key(text: str) -> str:
    """Normalize a concept name to a marker key."""
    s = text.strip().lower()
    s = re.sub(r'\(.*?\)', '', s)           # strip parentheticals
    s = re.sub(r'[^a-z0-9\s_]', '', s)      # strip special chars
    s = re.sub(r'\s+', '_', s.strip())       # spaces to underscores
    return s[:40]


def label_to_candidate_folders(label: str) -> list[str]:
    """Generate candidate alpha folder names from an interpretation label.

    Returns multiple candidates in priority order — the caller should check
    each against the actual alpha folder set.
    """
    candidates = []
    parts = label.split('_')
    author = parts[0].lower() if parts else label.lower()

    # 1. Full label lowercased + hyphenated (exact match for newer entries)
    #    e.g. Alexander_PhenomenonOfLife_2002_Book-1_Ch11 → alexander-phenomenonoflife-2002-book-1-ch11
    candidates.append(label.lower().replace('_', '-'))

    # 2. Author-early (common pattern for single-source entries)
    candidates.append(f"{author}-early")

    # 3. Author + second part (e.g. delanda-assemblage-early)
    if len(parts) >= 2:
        candidates.append(f"{author}-{parts[1].lower()}-early")

    # 4. Special patterns: CDR2 → sartre-CDR2-*
    if 'CDR2' in label:
        for part in parts:
            if part not in ('CDR2',) and part != parts[0] and not part.isdigit():
                candidates.append(f"{author}-CDR2-{part.lower()}")

    return candidates


# ---------------------------------------------------------------------------
# Interpretation file parsing
# ---------------------------------------------------------------------------

def parse_concept_table(text: str) -> list[dict]:
    """Extract concept mapping rows from interpretation tables."""
    mappings = []
    # Match table rows: | Concept | Mapping | Relationship... |
    # The relationship column often contains "confirms — explanation text"
    # so we match the keyword at the START of the third column, not the whole cell.
    table_pattern = re.compile(
        r'^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(confirms?|extends?|challenges?|novel)\b',
        re.IGNORECASE | re.MULTILINE
    )
    for m in table_pattern.finditer(text):
        concept = m.group(1).strip().strip('*').strip()
        mapping = m.group(2).strip().strip('*').strip()
        relationship = m.group(3).strip().lower()
        # Skip header rows
        if concept.lower() in ('concept', 'concept (from distillation)', 'source concept', '---', ''):
            continue
        if mapping.lower() in ('project mapping', 'mapping', '---', ''):
            continue
        mappings.append({
            'concept': concept,
            'maps_to': mapping,
            'relationship': relationship,
        })
    return mappings


def parse_forward_notes(text: str) -> list[dict]:
    """Extract forward note candidates from interpretation text."""
    notes = []
    # Match: §5.NN: description or §5.NN — description
    pattern = re.compile(r'§5\.(\d+)[:\s—–-]+\s*(.+?)(?:\n|$)')
    for m in pattern.finditer(text):
        number = m.group(1)
        description = m.group(2).strip().rstrip('*').strip()
        if description:
            notes.append({
                'number': f"5.{number}",
                'description': description,
            })
    return notes


def parse_integration_points(text: str) -> list[dict]:
    """Extract integration points (cross-source connections)."""
    points = []
    # Find "Integration Points" or "Cross-source" sections
    sections = re.split(r'^##\s+', text, flags=re.MULTILINE)
    for section in sections:
        if not re.match(r'(Integration Points|Cross.?source)', section, re.IGNORECASE):
            continue
        # Extract bullet points: - **concept**: description
        bullets = re.findall(
            r'[-*]\s+\*\*(.+?)\*\*:\s*(.+?)(?:\n|$)',
            section
        )
        for concept, desc in bullets:
            points.append({
                'concept': concept.strip(),
                'description': desc.strip(),
            })
        # Also extract cross-source mappings: Source × Source: description
        # Use only × (U+00D7 multiplication sign), NOT lowercase 'x' which
        # false-matches in words like "matrix", "taxonomy", "praxis".
        cross = re.findall(
            r'[-*]\s+(.+?)\s*×\s*(.+?):\s*(.+?)(?:\n|$)',
            section
        )
        for src1, src2, desc in cross:
            points.append({
                'concept': f"{src1.strip()} × {src2.strip()}",
                'description': desc.strip(),
                'is_cross_source': True,
            })
    return points


def parse_open_questions(text: str) -> list[str]:
    """Extract open questions from interpretation text."""
    questions = []
    sections = re.split(r'^##\s+', text, flags=re.MULTILINE)
    for section in sections:
        if not section.strip().startswith('Open Questions'):
            continue
        # Extract bullet points
        bullets = re.findall(r'[-*]\s+(.+?)(?:\n|$)', section)
        questions.extend(b.strip() for b in bullets if b.strip())
    return questions


def parse_interpretation(filepath: Path) -> dict:
    """Parse a single interpretation file into structured data."""
    text = filepath.read_text(encoding='utf-8')

    # Extract source label from filename
    label = filepath.stem  # e.g., Alexander_PhenomenonOfLife_2002_Book-1_Ch1-3

    # Extract header metadata
    source_match = re.search(r'>\s*Distillation:\s*(.+?)$', text, re.MULTILINE)
    distillation_ref = source_match.group(1).strip() if source_match else None

    return {
        'label': label,
        'filepath': str(filepath),
        'distillation_ref': distillation_ref,
        'concept_mappings': parse_concept_table(text),
        'forward_notes': parse_forward_notes(text),
        'integration_points': parse_integration_points(text),
        'open_questions': parse_open_questions(text),
    }


# ---------------------------------------------------------------------------
# Alpha index cross-reference
# ---------------------------------------------------------------------------

def load_alpha_sources(alpha_dir: Path) -> tuple[set[str], set[str]]:
    """Get source labels and folder names that already have alpha entries.

    Returns (distillation_labels, folder_names) where distillation_labels
    are normalized (no .md extension) and folder_names are the actual
    alpha index folder keys.

    Index structure:
      { "sources": { folder_name: { folder, cross_source_ids, ... } },
        "entries": { "w:N": { source, file, concept, distillation?, ... } } }
    """
    index_path = alpha_dir / 'index.json'
    if not index_path.exists():
        return set(), set()

    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return set(), set()

    distillation_labels = set()
    folder_names = set()

    # Collect folder names from sources section
    sources = index.get('sources', {})
    if isinstance(sources, dict):
        for folder_name in sources:
            if not folder_name.startswith('_'):
                folder_names.add(folder_name)

    # Collect distillation labels from entries section
    entries = index.get('entries', {})
    if isinstance(entries, dict):
        for entry_data in entries.values():
            if isinstance(entry_data, dict) and entry_data.get('distillation'):
                ref = entry_data['distillation']
                # Normalize: strip .md extension
                distillation_labels.add(ref.removesuffix('.md'))

    return distillation_labels, folder_names


def is_integrated(label: str, distillation_labels: set[str], folder_names: set[str]) -> bool:
    """Check if an interpretation label has corresponding alpha entries."""
    # Direct distillation reference match
    if label in distillation_labels:
        return True

    # Check candidate folder names against actual alpha folders
    for candidate in label_to_candidate_folders(label):
        if candidate in folder_names:
            return True

    return False


# ---------------------------------------------------------------------------
# Recovery output generation
# ---------------------------------------------------------------------------

def generate_alpha_entries(parsed: dict, distill_dir: Path) -> list[dict]:
    """Generate alpha-write JSON entries from parsed interpretation data."""
    entries = []
    label = parsed['label']
    # Use first candidate folder name (best guess for new entries)
    candidates = label_to_candidate_folders(label)
    source_folder = candidates[0] if candidates else label.lower().replace('_', '-')

    for mapping in parsed['concept_mappings']:
        key = normalize_key(mapping['concept'])
        if not key:
            continue

        body_parts = [
            f"## Definition\n{mapping['concept']}",
            f"## Project Mapping\n\n- **Maps to**: {mapping['maps_to']}\n- **Relationship**: {mapping['relationship']}",
        ]

        entries.append({
            'type': 'cross_source',
            'source_folder': source_folder,
            'distillation': label,
            'key': key,
            'maps_to': mapping['maps_to'],
            'ref': None,
            'suggest': None,
            'body': '\n\n'.join(body_parts),
        })

    return entries


def generate_convergence_entries(parsed: dict) -> list[dict]:
    """Generate convergence_web entries from cross-source connections."""
    entries = []

    for point in parsed['integration_points']:
        if not point.get('is_cross_source'):
            continue
        entries.append({
            'type': 'convergence_web',
            'thesis': {'label': point['concept'].split('×')[0].strip()},
            'athesis': {'label': point['concept'].split('×')[1].strip() if '×' in point['concept'] else ''},
            'synthesis': f"[independent_convergence] {point['description']}",
            'metathesis': '',
        })

    return entries


# ---------------------------------------------------------------------------
# Forward note registry
# ---------------------------------------------------------------------------

def build_forward_notes_registry(all_parsed: list[dict], existing_registry: dict | None = None) -> dict:
    """Build or update forward notes registry from all parsed interpretations."""
    if existing_registry:
        registry = existing_registry.copy()
    else:
        registry = {'next_number': 70, 'notes': {}}

    for parsed in all_parsed:
        for note in parsed['forward_notes']:
            num = note['number']
            if num not in registry['notes']:
                registry['notes'][num] = {
                    'source': parsed['label'],
                    'description': note['description'],
                    'status': 'candidate',
                    'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                }
            # Track the highest number seen
            num_int = int(num.split('.')[1]) if '.' in num else 0
            if num_int >= registry['next_number']:
                registry['next_number'] = num_int + 1

    return registry


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Recover orphaned distillations into alpha bin'
    )
    parser.add_argument('--interp-dir', required=True,
                        help='Path to interpretations directory')
    parser.add_argument('--distill-dir', required=True,
                        help='Path to distillations directory')
    parser.add_argument('--alpha-dir', required=True,
                        help='Path to alpha directory (.claude/buffer/alpha)')
    parser.add_argument('--output', default=None,
                        help='Output JSON file (default: stdout)')
    parser.add_argument('--forward-notes-out', default=None,
                        help='Output forward notes registry JSON')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview only, do not write files')

    args = parser.parse_args()

    interp_dir = Path(args.interp_dir).resolve()
    distill_dir = Path(args.distill_dir).resolve()
    alpha_dir = Path(args.alpha_dir).resolve()

    if not interp_dir.exists():
        print(f"Error: interpretations dir not found: {interp_dir}", file=sys.stderr)
        sys.exit(1)

    # --- Parse all interpretation files ---
    interp_files = sorted(interp_dir.glob('*.md'))
    print(f"Found {len(interp_files)} interpretation files", file=sys.stderr)

    all_parsed = []
    for f in interp_files:
        parsed = parse_interpretation(f)
        all_parsed.append(parsed)
        print(f"  {f.name}: {len(parsed['concept_mappings'])} mappings, "
              f"{len(parsed['forward_notes'])} fwd notes, "
              f"{len(parsed['integration_points'])} integration points",
              file=sys.stderr)

    # --- Cross-reference against alpha index ---
    # H9: warn if alpha/index.json exists with entries:{} but has other fields
    alpha_index_path = alpha_dir / 'index.json'
    if alpha_index_path.exists():
        try:
            _alpha_raw = json.loads(alpha_index_path.read_text(encoding='utf-8'))
            _entries = _alpha_raw.get('entries', {})
            if isinstance(_entries, dict) and not _entries and len(_alpha_raw) > 1:
                print("warning: alpha/index.json has structure but entries is empty"
                      " — possible data loss", file=sys.stderr)
        except (json.JSONDecodeError, OSError):
            pass

    distillation_labels, folder_names = load_alpha_sources(alpha_dir)
    print(f"\nAlpha index has {len(distillation_labels)} distillation refs, "
          f"{len(folder_names)} folders", file=sys.stderr)

    # Identify orphaned sources
    orphaned = []
    integrated = []
    for parsed in all_parsed:
        label = parsed['label']
        if is_integrated(label, distillation_labels, folder_names):
            integrated.append(parsed)
        else:
            orphaned.append(parsed)

    print(f"Integrated: {len(integrated)}, Orphaned: {len(orphaned)}", file=sys.stderr)

    if orphaned:
        print(f"\nOrphaned sources:", file=sys.stderr)
        for p in orphaned:
            print(f"  - {p['label']} ({len(p['concept_mappings'])} mappings)", file=sys.stderr)

    # --- Generate recovery entries ---
    all_entries = []
    for parsed in orphaned:
        entries = generate_alpha_entries(parsed, distill_dir)
        cw_entries = generate_convergence_entries(parsed)
        all_entries.extend(entries)
        all_entries.extend(cw_entries)

    print(f"\nGenerated {len(all_entries)} recovery entries "
          f"({len([e for e in all_entries if e['type'] == 'cross_source'])} cross_source, "
          f"{len([e for e in all_entries if e['type'] == 'convergence_web'])} convergence_web)",
          file=sys.stderr)

    # --- Build forward notes registry ---
    fn_registry = build_forward_notes_registry(all_parsed)
    collisions = {}
    for num, note in fn_registry['notes'].items():
        if num not in collisions:
            collisions[num] = []
        collisions[num].append(note['source'])

    multi_assigned = {k: v for k, v in collisions.items() if len(v) > 1}
    if multi_assigned:
        print(f"\n!! Forward note collisions detected:", file=sys.stderr)
        for num, sources in multi_assigned.items():
            print(f"  §{num}: assigned by {', '.join(sources)}", file=sys.stderr)

    print(f"\nForward notes registry: {len(fn_registry['notes'])} notes, "
          f"next_number: §5.{fn_registry['next_number']}", file=sys.stderr)

    # --- Output ---
    if args.dry_run:
        print(f"\n[DRY RUN] Would write {len(all_entries)} entries", file=sys.stderr)
        print(json.dumps({
            'entries': all_entries,
            'forward_notes': fn_registry,
            'orphaned_sources': [p['label'] for p in orphaned],
            'integrated_sources': [p['label'] for p in integrated],
        }, indent=2))
    else:
        # Write recovery entries
        output = json.dumps(all_entries, indent=2)
        if args.output:
            Path(args.output).write_text(output, encoding='utf-8')
            print(f"Wrote {len(all_entries)} entries to {args.output}", file=sys.stderr)
        else:
            print(output)

        # Write forward notes registry
        if args.forward_notes_out:
            Path(args.forward_notes_out).write_text(
                json.dumps(fn_registry, indent=2),
                encoding='utf-8'
            )
            print(f"Wrote forward notes registry to {args.forward_notes_out}",
                  file=sys.stderr)


if __name__ == '__main__':
    main()
