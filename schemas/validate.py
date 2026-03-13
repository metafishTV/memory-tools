#!/usr/bin/env python3
"""Advisory schema validation for session-buffer data files.

Usage:
    python validate.py alpha-entry <path-to-index.json>
    python validate.py convergence-web <path-to-index.json>
    python validate.py alpha-index <path-to-index.json>
    python validate.py manifest <path-to-manifest.json>
    python validate.py forward-notes <path-to-forward_notes.json>
    python validate.py hot-layer <path-to-handoff.json>
    python validate.py distill-stats <path-to-.distill_stats>
    python validate.py redistill-changelog <path-to-.redistill_changelog>
    python validate.py all <project-root>

Exit code 0 = clean, 1 = failures found.
"""

import io
import json
import os
import sys

# Force UTF-8 stdout/stderr on Windows when running as CLI
# (guard: only when __main__, not when imported by tests)
if sys.platform == 'win32' and __name__ == '__main__' and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    import jsonschema
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(2)


SCHEMA_DIR = os.path.dirname(os.path.abspath(__file__))

SCHEMA_FILES = {
    'alpha-entry': 'alpha-entry.schema.json',
    'convergence-web': 'convergence-web.schema.json',
    'alpha-index': 'alpha-index.schema.json',
    'manifest-source': 'manifest-source.schema.json',
    'forward-note': 'forward-note.schema.json',
    'hot-layer': 'hot-layer.schema.json',
    'distill-stats': 'distill-stats.schema.json',
    'redistill-changelog': 'redistill-changelog.schema.json',
}


def load_schema(name):
    """Load a JSON schema by short name."""
    path = os.path.join(SCHEMA_DIR, SCHEMA_FILES[name])
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def validate_data(schema_name, data):
    """Validate data against a named schema. Returns list of error strings."""
    schema = load_schema(schema_name)
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"  {'.'.join(str(p) for p in e.absolute_path)}: {e.message}"
        if e.absolute_path else f"  (root): {e.message}"
        for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]


def validate_file(schema_name, path):
    """Validate a JSON file against a named schema. Returns (errors, warnings)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        return [f"  Cannot read {path}: {exc}"], []

    errors = validate_data(schema_name, data)
    return errors, []


def validate_alpha_entries(path):
    """Validate individual entries inside an alpha index.json.

    Uses the entry sub-schema from alpha-index.schema.json rather than the
    write-input schemas (alpha-entry/convergence-web). The stored format
    differs from the write-input format — see CROSS_PLUGIN_CONTRACT.md.

    Handles production realities:
    - Framework entries (w:15-w:43) may lack 'type' and 'file' fields
    - All entries must have 'source' and 'concept'
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        return [f"  Cannot read {path}: {exc}"]

    errors = []
    entries = data.get('entries', {})

    # Extract the entry sub-schema from the alpha-index schema
    index_schema = load_schema('alpha-index')
    entry_schema = index_schema['properties']['entries']['patternProperties']['^(w|cw):\\d+$']
    validator = jsonschema.Draft202012Validator(entry_schema)

    for eid, entry in entries.items():
        for e in validator.iter_errors(entry):
            path_str = '.'.join(str(p) for p in e.absolute_path) if e.absolute_path else '(root)'
            errors.append(f"  {eid}.{path_str}: {e.message}")

    return errors


def validate_manifest_sources(path):
    """Validate individual source entries in a manifest.json."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        return [f"  Cannot read {path}: {exc}"]

    errors = []
    schema = load_schema('manifest-source')
    validator = jsonschema.Draft202012Validator(schema)

    sources = data.get('sources', {})
    for sname, sdata in sources.items():
        for e in validator.iter_errors(sdata):
            path_str = '.'.join(str(p) for p in e.absolute_path) if e.absolute_path else '(root)'
            errors.append(f"  sources.{sname}.{path_str}: {e.message}")

    return errors


def validate_forward_notes(path):
    """Validate individual notes in forward_notes.json."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        return [f"  Cannot read {path}: {exc}"]

    errors = []
    schema = load_schema('forward-note')
    validator = jsonschema.Draft202012Validator(schema)

    if 'next_number' not in data:
        errors.append("  (root): missing 'next_number' field")
    notes = data.get('notes', {})
    for nid, ndata in notes.items():
        for e in validator.iter_errors(ndata):
            path_str = '.'.join(str(p) for p in e.absolute_path) if e.absolute_path else '(root)'
            errors.append(f"  notes.{nid}.{path_str}: {e.message}")

    return errors


def validate_all(project_root):
    """Run all validations against a project directory. Returns dict of results."""
    results = {}

    # Alpha index
    alpha_index = os.path.join(project_root, '.claude', 'buffer', 'alpha', 'index.json')
    if os.path.exists(alpha_index):
        errs, _ = validate_file('alpha-index', alpha_index)
        entry_errs = validate_alpha_entries(alpha_index)
        results['alpha-index'] = errs + entry_errs
    else:
        results['alpha-index'] = ['  File not found (skipped)']

    # Manifest
    manifest = os.path.join(project_root, '.claude', 'skills', 'distill', 'manifest.json')
    if os.path.exists(manifest):
        results['manifest-sources'] = validate_manifest_sources(manifest)
    else:
        results['manifest-sources'] = ['  File not found (skipped)']

    # Forward notes
    fwd = os.path.join(project_root, '.claude', 'skills', 'distill', 'forward_notes.json')
    if os.path.exists(fwd):
        results['forward-notes'] = validate_forward_notes(fwd)
    else:
        results['forward-notes'] = ['  File not found (skipped)']

    # Hot layer
    hot = os.path.join(project_root, '.claude', 'buffer', 'handoff.json')
    if os.path.exists(hot):
        errs, _ = validate_file('hot-layer', hot)
        results['hot-layer'] = errs
    else:
        results['hot-layer'] = ['  File not found (skipped)']

    # Distill stats (temporary, may not exist)
    stats = os.path.join(project_root, '.claude', 'buffer', '.distill_stats')
    if os.path.exists(stats):
        errs, _ = validate_file('distill-stats', stats)
        results['distill-stats'] = errs
    else:
        results['distill-stats'] = ['  File not found (skipped)']

    return results


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)

    command = sys.argv[1]
    path = sys.argv[2]
    had_errors = False

    if command == 'all':
        results = validate_all(path)
        for name, errs in results.items():
            status = 'FAIL' if errs and 'not found' not in errs[0] else ('SKIP' if errs else 'OK')
            print(f"[{status}] {name}")
            for e in errs:
                print(e)
            if status == 'FAIL':
                had_errors = True
    elif command == 'alpha-entry':
        errs = validate_alpha_entries(path)
        for e in errs:
            print(e)
        had_errors = bool(errs)
    elif command == 'manifest':
        errs = validate_manifest_sources(path)
        for e in errs:
            print(e)
        had_errors = bool(errs)
    elif command == 'forward-notes':
        errs = validate_forward_notes(path)
        for e in errs:
            print(e)
        had_errors = bool(errs)
    elif command in SCHEMA_FILES:
        errs, _ = validate_file(command, path)
        for e in errs:
            print(e)
        had_errors = bool(errs)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__)
        sys.exit(2)

    sys.exit(1 if had_errors else 0)


if __name__ == '__main__':
    main()
