#!/usr/bin/env python3
"""One-time migration: backfill design doc forward notes into the registry.

Parses the Stage 3A design doc to extract all §5.1–§5.69 entries,
merges them with the existing registry (§5.70–§5.82 distillation candidates),
and converts the 15 mis-keyed amendment entries into cross_references on
the canonical design doc entries.

Usage:
    python migrate_forward_notes.py \
        --design-doc <path-to-design-doc.md> \
        --registry <path-to-forward_notes.json> \
        [--dry-run]
"""

import argparse
import json
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# §5.1–§5.18: extracted manually from the "Out of scope (bookmarked)" list
# because they don't have ## headers.  §5.9 does not exist.
# ---------------------------------------------------------------------------
EARLY_NOTES = {
    "5.1":  "Shadow ticks / anapressive per-agent tracking",
    "5.2":  "Shadow ticks / anapressive per-agent tracking (paired with §5.1)",
    "5.3":  "Durkheim disintegration mechanism",
    "5.4":  "Family groups / topology tracking",
    "5.5":  "Distance-based observation decay beyond Jaccard proxy",
    "5.6":  "Overconservation detection",
    "5.7":  "Praxitive time / deferral",
    "5.8":  "Consummation-completion as third disintegration pathway",
    # §5.9 does not exist in the design doc
    "5.10": "Filial inheritance / alliance mode / lineage tracking; asymmetric cross-metathesis roles",
    "5.11": "Praxitive syntegration vs. syntegrative praxis",
    "5.12": "Surplus vs. expressed value distinction",
    "5.13": "Praxistatic surplus / two-layer agent architecture",
    "5.14": "Artifact agents with substrate classes and containment rules",
    "5.15": "TAPS as four existential questions mapping",
    "5.16": "Innovation decay / forgetting mechanism",
    "5.17": "Agent-ensemble primacy and actualized vs. actualizing strata",
    "5.18": "Sartre-to-metathesis term mapping",
}


def parse_section_headers(doc_path):
    """Extract ## §5.NN Title lines from the design doc (§5.19–§5.69)."""
    pattern = re.compile(r'^## §(5\.\d+)\s+(.+)$')
    sections = {}
    with open(doc_path, 'r', encoding='utf-8-sig') as f:
        for line in f:
            m = pattern.match(line.strip())
            if m:
                num = m.group(1)
                title = m.group(2).strip()
                sections[num] = title
    return sections


def build_design_entries(early, sections):
    """Create registry entries for all design doc forward notes."""
    entries = {}
    for num, desc in {**early, **sections}.items():
        entries[num] = {
            "source": "design_doc",
            "description": desc,
            "status": "bookmarked",
            "date": "2026-02-26",
            "origin": "design_doc",
        }
    return entries


def merge_registries(design_entries, existing_registry):
    """Merge design doc entries with existing registry.

    - §5.70+: keep as-is (genuine distillation candidates)
    - §5.1–§5.69 that exist in both: design doc is canonical,
      distillation entry becomes a cross_reference
    - §5.1–§5.69 only in design doc: add as new entries
    """
    existing_notes = existing_registry.get('notes', {})
    merged = {}

    # First: add all design doc entries
    for num, entry in sorted(design_entries.items(), key=lambda x: float(x[0])):
        merged[num] = dict(entry)

        # Check if distillation had an amendment for this number
        if num in existing_notes:
            distill_entry = existing_notes[num]
            merged[num]['cross_references'] = [{
                'source': distill_entry.get('source', 'unknown'),
                'description': distill_entry.get('description', ''),
                'date': distill_entry.get('date', ''),
            }]

    # Then: add §5.70+ distillation candidates as-is
    for num, entry in existing_notes.items():
        sub_num = int(num.split('.')[1])
        if sub_num >= 70 and num not in merged:
            merged[num] = dict(entry)

    return merged


def main():
    parser = argparse.ArgumentParser(description='Migrate forward notes')
    parser.add_argument('--design-doc', required=True, help='Path to design doc')
    parser.add_argument('--registry', required=True, help='Path to forward_notes.json')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing')
    args = parser.parse_args()

    doc_path = Path(args.design_doc)
    reg_path = Path(args.registry)

    # Parse design doc sections
    sections = parse_section_headers(doc_path)
    print(f"Parsed {len(sections)} section headers from design doc (§5.19–§5.69)")

    # Build design doc entries
    design_entries = build_design_entries(EARLY_NOTES, sections)
    print(f"Total design doc entries: {len(design_entries)} (§5.1–§5.69, excl §5.9)")

    # Load existing registry
    if reg_path.exists():
        with open(reg_path, 'r', encoding='utf-8-sig') as f:
            existing = json.load(f)
        existing_notes = existing.get('notes', {})
        print(f"Existing registry: {len(existing_notes)} entries, next_number={existing.get('next_number')}")
    else:
        existing = {'next_number': 83, 'notes': {}}
        print("No existing registry found — creating new")

    # Identify amendments (distillation entries keyed to design doc numbers)
    amendments = [n for n in existing_notes if int(n.split('.')[1]) < 70]
    new_candidates = [n for n in existing_notes if int(n.split('.')[1]) >= 70]
    print(f"  Amendments to migrate: {len(amendments)} -> {amendments}")
    print(f"  New candidates to keep: {len(new_candidates)} -> {new_candidates}")

    # Merge
    merged = merge_registries(design_entries, existing)

    # Sort by integer sub-number (5.5 = item 5, 5.50 = item 50 — NOT the same)
    def sort_key(item):
        parts = item[0].split('.')
        return (int(parts[0]), int(parts[1]))
    sorted_merged = dict(sorted(merged.items(), key=sort_key))

    result = {
        'next_number': existing.get('next_number', 83),
        'notes': sorted_merged,
    }

    # Stats
    design_count = sum(1 for v in sorted_merged.values() if v.get('origin') == 'design_doc')
    distill_count = len(sorted_merged) - design_count
    xref_count = sum(1 for v in sorted_merged.values() if 'cross_references' in v)
    print(f"\nMerged registry: {len(sorted_merged)} total entries")
    print(f"  {design_count} design doc entries (origin=design_doc)")
    print(f"  {distill_count} distillation candidates (§5.70+)")
    print(f"  {xref_count} entries with cross-references from distillation")

    if args.dry_run:
        print("\n--- DRY RUN (not writing) ---")
        dry_path = reg_path.parent / 'forward_notes_PREVIEW.json'
        with open(dry_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Preview written to {dry_path}")
    else:
        with open(reg_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nWritten to {reg_path}")


if __name__ == '__main__':
    main()
