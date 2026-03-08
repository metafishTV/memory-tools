#!/usr/bin/env python3
"""
Alpha Bin Migration Script

Decomposes concept_map and convergence_web from handoff-warm.json into
individual referent files under .claude/buffer/alpha/.

Usage:
    python migrate_to_alpha.py --buffer-dir /path/to/.claude/buffer/
    python migrate_to_alpha.py --buffer-dir /path/to/.claude/buffer/ --dry-run

One-time migration. Safe to re-run (skips if alpha/ already exists unless --force).
"""

import sys
import os
import io
import json
import re
import argparse
from pathlib import Path
from datetime import date

# Guard: only wrap when running as main script, not when imported by tests
if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRAMEWORK_GROUPS = [
    'foundational_triad', 'dialectic', 'T', 'A', 'P', 'S', 'RIP'
]

# Map key prefixes to folder names for pre-distill-skill entries
SOURCE_PREFIX_MAP = {
    'Sartre': 'sartre-early',
    'Levinas': 'levinas-early',
    'Emery': 'emery-early',
    'D&G': 'dg-early',
    'DG': 'dg-early',
    'Lizier': 'lizier-early',
    'Turchin': 'turchin-early',
    'RB': 'ruesch-bateson-early',
    'R&B': 'ruesch-bateson-early',
    'Viz': '_mixed-early',
    'Cortes': 'cortes-early',
    'DeLanda': 'delanda-early',
    'Easwaran': 'easwaran-early',
    'Taalbi': 'taalbi-early',
    'Unificity': 'unificity',
    'Easwaran_Gita': 'easwaran-gita-early',
    'Easwaran_Glossary': 'easwaran-glossary-early',
    'DeLanda_AssemblageTheory': 'delanda-assemblage-early',
    'Sartre_CDR2_Envelopment': 'sartre-CDR2-envelopment',
    'Sartre_CDR2': 'sartre-CDR2-early',
    '_forward_note': '_forward-notes',
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')


def write_md(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def kebab(name):
    """Convert source label to kebab-case folder name."""
    # Replace underscores and spaces with hyphens
    s = re.sub(r'[_\s]+', '-', name)
    # Remove non-alphanumeric except hyphens
    s = re.sub(r'[^a-zA-Z0-9\-]', '', s)
    # Collapse multiple hyphens
    s = re.sub(r'-+', '-', s).strip('-')
    return s.lower()


def parse_source_prefix(key):
    """Extract source prefix from a cross_source key like 'Sartre:totalization'."""
    if not key or ':' not in key:
        return None
    prefix = key.split(':')[0].strip()
    return prefix



def prefix_to_folder(prefix):
    """Map a source prefix to a folder name."""
    if not prefix:
        return '_mixed-early'
    # Check exact matches first
    if prefix in SOURCE_PREFIX_MAP:
        return SOURCE_PREFIX_MAP[prefix]
    # Check case-insensitive partial matches
    for k, v in SOURCE_PREFIX_MAP.items():
        if prefix.lower().startswith(k.lower()):
            return v
    # Derive from prefix
    return kebab(prefix) + '-early'


def id_num(entry_id):
    """Extract numeric part from an ID like 'w:65' -> 65, 'cw:7' -> 7."""
    parts = entry_id.split(':')
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


def pad_id(entry_id):
    """Pad ID for filename: w:65 -> w065, cw:7 -> cw007."""
    parts = entry_id.split(':')
    if len(parts) == 2:
        try:
            num = int(parts[1])
            prefix = parts[0]
            return f"{prefix}{num:03d}"
        except ValueError:
            pass
    return entry_id.replace(':', '')


# ---------------------------------------------------------------------------
# Schema normalization
# ---------------------------------------------------------------------------

# Canonical fields for each entry type. Normalization ensures every entry
# carries the same set of fields regardless of which distillation session
# created it. Missing fields get sensible defaults; variant field names
# (e.g. 'source' used where 'key' is expected) are mapped to canonical form.

CROSS_SOURCE_SCHEMA = {
    'id': '',           # required: w:N
    'key': '',          # Source:concept canonical identifier
    'maps_to': '',      # what it maps to in sigma-TAP
    'ref': '',          # section / page reference
    'suggest': None,    # nullable
    '_origin': '',      # normalized: how we inferred the routing
}

CONVERGENCE_WEB_SCHEMA = {
    'id': '',           # required: cw:N
    'thesis': {},       # { ref, label }
    'athesis': {},      # { ref, label }
    'synthesis': '',    # [type_tag] ...
    'metathesis': '',   # ...
}


def normalize_cross_source(entry):
    """Normalize a cross_source entry to canonical schema.

    Handles three known variant schemas:
    1. Standard: has 'key' field with Source:concept format
    2. Source-field: has 'source' field instead of 'key' (Easwaran, DeLanda)
    3. Ref-inferred: no key or source, but ref field contains source info
    4. Unattributed: forward notes and internal concepts

    Returns a new dict with all canonical fields populated.
    """
    norm = dict(CROSS_SOURCE_SCHEMA)
    norm['id'] = entry.get('id', '')
    norm['maps_to'] = entry.get('maps_to', '')
    norm['ref'] = entry.get('ref', '') or ''
    norm['suggest'] = entry.get('suggest')

    # Determine key via fallback chain
    key = entry.get('key')
    if key and ':' in str(key):
        norm['key'] = key
        norm['_origin'] = 'key_field'
    elif entry.get('source') and ':' in str(entry.get('source', '')):
        norm['key'] = entry['source']
        norm['_origin'] = 'source_field'
    elif 'Sartre_CritiqueDR2_1991_Envelopment' in norm['ref']:
        concept = norm['maps_to'].split(',')[0].strip() if norm['maps_to'] else 'unmapped'
        norm['key'] = f"Sartre_CDR2_Envelopment:{concept}"
        norm['_origin'] = 'ref_inferred:sartre_CDR2'
    elif 'Sartre_CritiqueDR2' in norm['ref']:
        concept = norm['maps_to'].split(',')[0].strip() if norm['maps_to'] else 'unmapped'
        norm['key'] = f"Sartre_CDR2:{concept}"
        norm['_origin'] = 'ref_inferred:sartre_CDR2'
    elif norm['ref'].startswith(('forward_note:', '§5.')):
        concept = norm['maps_to'].split(',')[0].strip() if norm['maps_to'] else 'unmapped'
        norm['key'] = f"_forward_note:{concept}"
        norm['_origin'] = 'forward_note'
    else:
        concept = norm['maps_to'].split(',')[0].strip() if norm['maps_to'] else 'unmapped'
        norm['key'] = f"_forward_note:{concept}"
        norm['_origin'] = 'unattributed'

    return norm


def normalize_convergence_web(entry):
    """Normalize a convergence_web entry to canonical schema."""
    norm = dict(CONVERGENCE_WEB_SCHEMA)
    norm['id'] = entry.get('id', '')
    norm['thesis'] = entry.get('thesis', {})
    norm['athesis'] = entry.get('athesis', {})
    norm['synthesis'] = entry.get('synthesis', '')
    norm['metathesis'] = entry.get('metathesis', '')
    # Ensure thesis/athesis have ref and label
    for field in ('thesis', 'athesis'):
        if 'ref' not in norm[field]:
            norm[field]['ref'] = '?'
        if 'label' not in norm[field]:
            norm[field]['label'] = '?'
    return norm


# ---------------------------------------------------------------------------
# Referent file generators
# ---------------------------------------------------------------------------

def make_framework_md(group_name, entries):
    """Generate markdown for a framework group file."""
    lines = [f"# {group_name.replace('_', ' ').title()}"]
    lines.append(f"**Framework group**: {group_name}")
    lines.append("**Framework**: true")
    lines.append("")

    for entry in entries:
        eid = entry.get('id', '?')
        if '_meta' in entry:
            lines.append(f"## {eid} -- [meta]")
            lines.append(entry['_meta'])
        else:
            term = entry.get('term', '?')
            lines.append(f"## {eid} -- {term}")
            # Include all fields
            if 'base' in entry:
                lines.append(entry['base'])
            for k, v in entry.items():
                if k in ('id', 'term', 'base', '_meta'):
                    continue
                if v is not None and v != [] and v != '':
                    lines.append(f"**{k}**: {json.dumps(v) if isinstance(v, (list, dict)) else v}")
        lines.append("")

    return '\n'.join(lines)


def make_cross_source_md(entry, source_label=None):
    """Generate markdown for an individual cross_source referent file."""
    eid = entry.get('id', '?')
    key = entry.get('key') or entry.get('source') or '?'
    maps_to = entry.get('maps_to', '')
    ref = entry.get('ref', '')
    suggest = entry.get('suggest')

    lines = [f"# {eid} -- {key}"]
    if source_label:
        lines.append(f"**Source**: {source_label} | **ID**: {eid} | **Type**: cross_source")
    else:
        lines.append(f"**ID**: {eid} | **Type**: cross_source")
    lines.append("")
    lines.append("## Mapping")
    lines.append(f"**Key**: {key}")
    lines.append(f"**Maps to**: {maps_to}")
    if ref:
        lines.append(f"**Ref**: {ref}")
    if suggest is not None:
        lines.append(f"**Suggest**: {json.dumps(suggest)}")
    lines.append("")

    return '\n'.join(lines)


def make_convergence_web_md(entry):
    """Generate markdown for an individual convergence_web referent file."""
    eid = entry.get('id', '?')
    thesis = entry.get('thesis', {})
    athesis = entry.get('athesis', {})
    synthesis = entry.get('synthesis', '')
    metathesis = entry.get('metathesis', '')

    t_label = thesis.get('label', '?')
    a_label = athesis.get('label', '?')
    t_ref = thesis.get('ref', '?')
    a_ref = athesis.get('ref', '?')

    lines = [f"# {eid} -- {t_label} x {a_label}"]
    lines.append(f"**ID**: {eid} | **Type**: convergence_web")
    lines.append("")
    lines.append("## Tetradic Structure")
    lines.append(f"**Thesis**: {t_ref} ({t_label})")
    lines.append(f"**Athesis**: {a_ref} ({a_label})")
    lines.append(f"**Synthesis**: {synthesis}")
    lines.append(f"**Metathesis**: {metathesis}")
    lines.append("")

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Source grouping for cross_source entries
# ---------------------------------------------------------------------------

def group_cross_source_by_source(entries):
    """Normalize and group cross_source entries by source prefix.

    Returns dict of folder -> list of normalized entries.
    """
    groups = {}
    for entry in entries:
        norm = normalize_cross_source(entry)
        prefix = parse_source_prefix(norm['key'])
        folder = prefix_to_folder(prefix)
        groups.setdefault(folder, []).append(norm)
    return groups


def group_convergence_web_by_thesis(entries):
    """Normalize and group convergence_web entries by thesis source prefix."""
    groups = {}
    for entry in entries:
        norm = normalize_convergence_web(entry)
        label = norm['thesis'].get('label', '')
        prefix = parse_source_prefix(label)
        folder = prefix_to_folder(prefix)
        groups.setdefault(folder, []).append(norm)
    return groups


# ---------------------------------------------------------------------------
# Index builder
# ---------------------------------------------------------------------------

def build_index(alpha_dir, framework_entries, cs_groups, cw_groups):
    """Build the alpha index.json from written files."""
    index = {
        "schema_version": 1,
        "created": date.today().isoformat(),
        "last_updated": date.today().isoformat(),
        "summary": {
            "total_cross_source": 0,
            "total_convergence_web": 0,
            "total_framework": 0,
            "total_sources": 0
        },
        "sources": {},
        "entries": {},
        "concept_index": {},
        "source_index": {}
    }

    # Framework entries
    fw_count = 0
    for group_name, entries in framework_entries.items():
        for entry in entries:
            eid = entry.get('id')
            if not eid:
                continue
            filename = f"_framework/{group_name}.md"
            concept = entry.get('term', entry.get('_meta', group_name))
            index['entries'][eid] = {
                "source": "_framework",
                "file": filename,
                "concept": concept,
                "group": group_name
            }
            fw_count += 1

    index['sources']['_framework'] = {
        "framework": True,
        "folder": "_framework",
        "entry_count": fw_count,
        "groups": list(framework_entries.keys())
    }
    index['summary']['total_framework'] = fw_count

    # Cross-source entries
    cs_total = 0
    all_sources = set()
    for folder, entries in cs_groups.items():
        source_ids = []
        for entry in entries:
            eid = entry.get('id')
            if not eid:
                continue
            # Entries are already normalized by group_cross_source_by_source
            canonical_key = entry.get('key', '')
            padded = pad_id(eid)
            filename = f"{folder}/{padded}.md"
            concept = canonical_key
            index['entries'][eid] = {
                "source": folder,
                "file": filename,
                "concept": concept
            }
            source_ids.append(eid)
            cs_total += 1

            # Build concept_index
            concept_name = canonical_key.split(':')[1] if ':' in canonical_key else canonical_key
            concept_name_lower = concept_name.strip().lower()
            if concept_name_lower:
                index['concept_index'].setdefault(concept_name_lower, []).append(eid)

            # Build source_index
            prefix = parse_source_prefix(canonical_key)
            if prefix and not prefix.startswith('_'):
                index['source_index'].setdefault(prefix, []).append(eid)

        all_sources.add(folder)
        if folder not in index['sources']:
            index['sources'][folder] = {
                "folder": folder,
                "cross_source_ids": source_ids,
                "convergence_web_ids": [],
                "entry_count": len(source_ids)
            }
        else:
            index['sources'][folder]['cross_source_ids'] = source_ids
            index['sources'][folder]['entry_count'] = (
                index['sources'][folder].get('entry_count', 0) + len(source_ids)
            )

    index['summary']['total_cross_source'] = cs_total

    # Convergence web entries
    cw_total = 0
    for folder, entries in cw_groups.items():
        cw_ids = []
        for entry in entries:
            eid = entry.get('id')
            if not eid:
                continue
            padded = pad_id(eid)
            filename = f"{folder}/{padded}.md"

            thesis_label = entry.get('thesis', {}).get('label', '?')
            athesis_label = entry.get('athesis', {}).get('label', '?')
            concept = f"{thesis_label} x {athesis_label}"

            index['entries'][eid] = {
                "source": folder,
                "file": filename,
                "concept": concept,
                "type": "convergence_web"
            }
            cw_ids.append(eid)
            cw_total += 1

        all_sources.add(folder)
        if folder not in index['sources']:
            index['sources'][folder] = {
                "folder": folder,
                "cross_source_ids": [],
                "convergence_web_ids": cw_ids,
                "entry_count": len(cw_ids)
            }
        else:
            index['sources'][folder].setdefault('convergence_web_ids', []).extend(cw_ids)
            index['sources'][folder]['entry_count'] = (
                index['sources'][folder].get('entry_count', 0) + len(cw_ids)
            )

    index['summary']['total_convergence_web'] = cw_total
    index['summary']['total_sources'] = len(all_sources)

    return index


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------

def migrate(buffer_dir, dry_run=False, force=False):
    alpha_dir = os.path.join(buffer_dir, 'alpha')

    if os.path.exists(alpha_dir) and not force:
        print(f"Alpha directory already exists at {alpha_dir}")
        print("Use --force to overwrite.")
        return False

    warm_path = os.path.join(buffer_dir, 'handoff-warm.json')
    hot_path = os.path.join(buffer_dir, 'handoff.json')

    if not os.path.exists(warm_path):
        print(f"No warm layer found at {warm_path}")
        return False

    warm = read_json(warm_path)
    concept_map = warm.get('concept_map', {})
    convergence_web = warm.get('convergence_web', {})

    # --- Extract framework groups ---
    framework_entries = {}
    for group_name in FRAMEWORK_GROUPS:
        entries = concept_map.get(group_name, [])
        if entries:
            framework_entries[group_name] = entries

    # --- Extract cross_source entries ---
    cross_source = concept_map.get('cross_source', [])
    cs_groups = group_cross_source_by_source(cross_source)

    # --- Extract convergence_web entries ---
    cw_entries = convergence_web.get('entries', [])
    cw_groups = group_convergence_web_by_thesis(cw_entries)

    # --- Summary ---
    fw_count = sum(len(v) for v in framework_entries.values())
    cs_count = len(cross_source)
    cw_count = len(cw_entries)
    print(f"Migration plan:")
    print(f"  Framework entries: {fw_count} across {len(framework_entries)} groups")
    print(f"  Cross-source entries: {cs_count} across {len(cs_groups)} source folders")
    print(f"  Convergence web entries: {cw_count} across {len(cw_groups)} source folders")
    print(f"  Total referent files to write: {fw_count + cs_count + cw_count + len(framework_entries)}")
    print()

    if dry_run:
        print("--- DRY RUN ---")
        print("Source folders that would be created:")
        all_folders = set()
        all_folders.add('_framework')
        all_folders.update(cs_groups.keys())
        all_folders.update(cw_groups.keys())
        for f in sorted(all_folders):
            cs_n = len(cs_groups.get(f, []))
            cw_n = len(cw_groups.get(f, []))
            fw_n = len(framework_entries.get(f, []))
            parts = []
            if fw_n:
                parts.append(f"{fw_n} framework")
            if cs_n:
                parts.append(f"{cs_n} cross_source")
            if cw_n:
                parts.append(f"{cw_n} convergence_web")
            print(f"  {f}/  ({', '.join(parts)})")
        print()
        print("Warm layer would shrink to: decisions_archive + validation_log")
        da = warm.get('decisions_archive', [])
        vl = warm.get('validation_log', [])
        remaining = len(json.dumps({"schema_version": warm.get("schema_version"),
                                     "layer": "warm",
                                     "decisions_archive": da,
                                     "validation_log": vl,
                                     "alpha_ref": "alpha/index.json"}, indent=2).split('\n'))
        print(f"  decisions_archive: {len(da)} entries")
        print(f"  validation_log: {len(vl)} entries")
        print(f"  Estimated warm size after: ~{remaining} lines")
        return True

    # --- Write files ---
    print("Writing alpha bin files...")

    # Framework groups
    for group_name, entries in framework_entries.items():
        md = make_framework_md(group_name, entries)
        path = os.path.join(alpha_dir, '_framework', f'{group_name}.md')
        write_md(path, md)
        print(f"  _framework/{group_name}.md ({len(entries)} entries)")

    # Cross-source referents
    skipped_cs = 0
    for folder, entries in cs_groups.items():
        written = 0
        for entry in entries:
            eid = entry.get('id', '')
            if not eid:
                skipped_cs += 1
                continue
            padded = pad_id(eid)
            md = make_cross_source_md(entry, source_label=folder)
            path = os.path.join(alpha_dir, folder, f'{padded}.md')
            write_md(path, md)
            written += 1
        print(f"  {folder}/ ({written} cross_source files)")
    if skipped_cs:
        print(f"  (skipped {skipped_cs} entries with no ID)")

    # Convergence web referents
    skipped_cw = 0
    for folder, entries in cw_groups.items():
        written = 0
        for entry in entries:
            eid = entry.get('id', '')
            if not eid:
                skipped_cw += 1
                continue
            padded = pad_id(eid)
            md = make_convergence_web_md(entry)
            path = os.path.join(alpha_dir, folder, f'{padded}.md')
            write_md(path, md)
            written += 1
        print(f"  {folder}/ ({written} convergence_web files)")
    if skipped_cw:
        print(f"  (skipped {skipped_cw} entries with no ID)")

    # Build and write index
    print("\nBuilding index.json...")
    index = build_index(alpha_dir, framework_entries, cs_groups, cw_groups)
    write_json(os.path.join(alpha_dir, 'index.json'), index)
    print(f"  {index['summary']['total_cross_source']} cross_source entries")
    print(f"  {index['summary']['total_convergence_web']} convergence_web entries")
    print(f"  {index['summary']['total_framework']} framework entries")
    print(f"  {index['summary']['total_sources']} source folders")

    # Rewrite warm layer (strip concept_map and convergence_web)
    print("\nRewriting warm layer...")
    new_warm = {
        "schema_version": warm.get("schema_version", 2),
        "layer": "warm",
        "alpha_ref": "alpha/index.json",
        "decisions_archive": warm.get("decisions_archive", []),
        "validation_log": warm.get("validation_log", [])
    }
    write_json(warm_path, new_warm)
    new_warm_lines = len(json.dumps(new_warm, indent=2).split('\n'))
    print(f"  Warm layer: 3680 lines -> {new_warm_lines} lines")

    # Update hot layer
    if os.path.exists(hot_path):
        print("Updating hot layer...")
        hot = read_json(hot_path)
        hot['alpha_ref'] = 'alpha/index.json'
        # Update digest meta to note migration
        cmd = hot.get('concept_map_digest', {})
        cmd_meta = cmd.get('_meta', {})
        cmd_meta['migrated_to_alpha'] = date.today().isoformat()
        cmd['_meta'] = cmd_meta
        hot['concept_map_digest'] = cmd

        cwd = hot.get('convergence_web_digest', {})
        cwd_meta = cwd.get('_meta', {})
        cwd_meta['migrated_to_alpha'] = date.today().isoformat()
        cwd['_meta'] = cwd_meta
        hot['convergence_web_digest'] = cwd

        write_json(hot_path, hot)
        print("  Added alpha_ref, marked digests as migrated")

    # Validate
    print("\nValidating...")
    all_original_ids = set()
    for group_name in FRAMEWORK_GROUPS:
        for entry in concept_map.get(group_name, []):
            if 'id' in entry:
                all_original_ids.add(entry['id'])
    for entry in cross_source:
        if 'id' in entry:
            all_original_ids.add(entry['id'])
    for entry in cw_entries:
        if 'id' in entry:
            all_original_ids.add(entry['id'])

    index_ids = set(index['entries'].keys())
    missing = all_original_ids - index_ids
    extra = index_ids - all_original_ids

    if missing:
        print(f"  WARNING: {len(missing)} IDs missing from index: {sorted(missing)[:10]}...")
    if extra:
        print(f"  WARNING: {len(extra)} extra IDs in index: {sorted(extra)[:10]}...")
    if not missing and not extra:
        print(f"  All {len(all_original_ids)} IDs present in index. Migration complete.")

    print(f"\nDone. Alpha bin written to {alpha_dir}")
    return True


# ---------------------------------------------------------------------------
# Index rebuild (from existing alpha files on disk)
# ---------------------------------------------------------------------------

def parse_referent_md(filepath):
    """Parse a referent .md file back into structured data.

    Reads the header and ## sections to reconstruct entry metadata.
    Returns (entry_type, entry_dict) or (None, None) on failure.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None, None

    lines = content.strip().split('\n')
    if not lines:
        return None, None

    # Parse header: "# w:44 -- Sartre:totalization" or "# cw:1 -- ..."
    header = lines[0]
    entry_id = ''
    concept = ''
    if header.startswith('# '):
        rest = header[2:]
        if ' -- ' in rest:
            entry_id, concept = rest.split(' -- ', 1)
        else:
            entry_id = rest

    if not entry_id:
        return None, None

    # Detect type from second line
    entry_type = 'cross_source'
    for line in lines[1:5]:
        if 'convergence_web' in line:
            entry_type = 'convergence_web'
            break

    entry = {'id': entry_id, 'concept': concept}

    # Parse key-value pairs from **Key**: Value lines
    for line in lines:
        if line.startswith('**Key**: '):
            entry['key'] = line[len('**Key**: '):]
        elif line.startswith('**Maps to**: '):
            entry['maps_to'] = line[len('**Maps to**: '):]
        elif line.startswith('**Ref**: '):
            entry['ref'] = line[len('**Ref**: '):]
        elif line.startswith('**Thesis**: '):
            entry['thesis_line'] = line[len('**Thesis**: '):]
        elif line.startswith('**Athesis**: '):
            entry['athesis_line'] = line[len('**Athesis**: '):]
        elif line.startswith('**Synthesis**: '):
            entry['synthesis'] = line[len('**Synthesis**: '):]
        elif line.startswith('**Metathesis**: '):
            entry['metathesis'] = line[len('**Metathesis**: '):]
        elif line.startswith('**Source**: '):
            entry['source_label'] = line[len('**Source**: '):].split(' | ')[0]

    return entry_type, entry


def parse_framework_md(filepath, group_name):
    """Parse a framework group .md file back into entry list."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return []

    entries = []
    current_id = None
    current_concept = None

    for line in content.split('\n'):
        if line.startswith('## '):
            rest = line[3:]
            if ' -- ' in rest:
                current_id, current_concept = rest.split(' -- ', 1)
            else:
                current_id = rest
                current_concept = group_name
            entries.append({
                'id': current_id,
                'concept': current_concept,
                'group': group_name
            })

    return entries


def rebuild_index(buffer_dir):
    """Rebuild index.json by scanning existing alpha .md files on disk.

    This is the architectural recovery mechanism: if index.json is lost
    or corrupted, the individual referent files contain all necessary
    metadata to reconstruct the full index.
    """
    alpha_dir = os.path.join(buffer_dir, 'alpha')
    if not os.path.isdir(alpha_dir):
        print(f"No alpha directory at {alpha_dir}")
        return False

    index = {
        "schema_version": 1,
        "created": date.today().isoformat(),
        "last_updated": date.today().isoformat(),
        "rebuilt": True,
        "summary": {
            "total_cross_source": 0,
            "total_convergence_web": 0,
            "total_framework": 0,
            "total_sources": 0
        },
        "sources": {},
        "entries": {},
        "concept_index": {},
        "source_index": {}
    }

    all_sources = set()

    # Scan _framework/ first
    fw_dir = os.path.join(alpha_dir, '_framework')
    fw_count = 0
    if os.path.isdir(fw_dir):
        groups = []
        for fname in sorted(os.listdir(fw_dir)):
            if not fname.endswith('.md'):
                continue
            group_name = fname[:-3]  # strip .md
            groups.append(group_name)
            entries = parse_framework_md(os.path.join(fw_dir, fname), group_name)
            for entry in entries:
                eid = entry['id']
                index['entries'][eid] = {
                    "source": "_framework",
                    "file": f"_framework/{fname}",
                    "concept": entry.get('concept', group_name),
                    "group": group_name
                }
                fw_count += 1

        index['sources']['_framework'] = {
            "framework": True,
            "folder": "_framework",
            "entry_count": fw_count,
            "groups": groups
        }
    index['summary']['total_framework'] = fw_count

    # Scan all other folders
    cs_total = 0
    cw_total = 0
    for folder_name in sorted(os.listdir(alpha_dir)):
        folder_path = os.path.join(alpha_dir, folder_name)
        if not os.path.isdir(folder_path) or folder_name == '_framework':
            continue

        all_sources.add(folder_name)
        cs_ids = []
        cw_ids = []

        for fname in sorted(os.listdir(folder_path)):
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(folder_path, fname)
            entry_type, entry = parse_referent_md(fpath)
            if not entry or not entry.get('id'):
                continue

            eid = entry['id']
            rel_file = f"{folder_name}/{fname}"

            if entry_type == 'convergence_web':
                concept = entry.get('concept', '?')
                index['entries'][eid] = {
                    "source": folder_name,
                    "file": rel_file,
                    "concept": concept,
                    "type": "convergence_web"
                }
                cw_ids.append(eid)
                cw_total += 1
            else:
                key = entry.get('key', entry.get('concept', '?'))
                index['entries'][eid] = {
                    "source": folder_name,
                    "file": rel_file,
                    "concept": key
                }
                cs_ids.append(eid)
                cs_total += 1

                # concept_index
                concept_name = key.split(':')[1] if ':' in key else key
                concept_lower = concept_name.strip().lower()
                if concept_lower:
                    index['concept_index'].setdefault(concept_lower, []).append(eid)

                # source_index
                prefix = parse_source_prefix(key)
                if prefix and not prefix.startswith('_'):
                    index['source_index'].setdefault(prefix, []).append(eid)

        index['sources'][folder_name] = {
            "folder": folder_name,
            "cross_source_ids": cs_ids,
            "convergence_web_ids": cw_ids,
            "entry_count": len(cs_ids) + len(cw_ids)
        }

    index['summary']['total_cross_source'] = cs_total
    index['summary']['total_convergence_web'] = cw_total
    index['summary']['total_sources'] = len(all_sources)

    # Write index
    idx_path = os.path.join(alpha_dir, 'index.json')
    write_json(idx_path, index)

    print(f"Index rebuilt from files on disk:")
    print(f"  {fw_count} framework entries")
    print(f"  {cs_total} cross_source entries")
    print(f"  {cw_total} convergence_web entries")
    print(f"  {len(all_sources)} source folders")
    print(f"  {fw_count + cs_total + cw_total} total entries")
    print(f"\nWritten to {idx_path}")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Migrate buffer warm layer to alpha bin')
    parser.add_argument('--buffer-dir', required=True, help='Path to .claude/buffer/ directory')
    parser.add_argument('--dry-run', action='store_true', help='Show what would happen without writing')
    parser.add_argument('--force', action='store_true', help='Overwrite existing alpha directory')
    parser.add_argument('--rebuild-index', action='store_true',
                        help='Rebuild index.json from existing alpha files on disk')
    args = parser.parse_args()

    if not os.path.isdir(args.buffer_dir):
        print(f"Error: {args.buffer_dir} is not a directory")
        sys.exit(1)

    if args.rebuild_index:
        success = rebuild_index(args.buffer_dir)
    else:
        success = migrate(args.buffer_dir, dry_run=args.dry_run, force=args.force)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
