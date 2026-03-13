#!/usr/bin/env python3
"""distill_manifest.py — Distillation manifest engine (v2.0).

Single source of truth for distillation state: what has been distilled,
how well, what connects to what. Provides polymorphic views for different
consumers (Pass 4, integrate, sigma hook, health checks).

Commands:
  init        Bootstrap manifest from existing alpha/interpretations
  update      Add/update a source entry after distillation
  query       Polymorphic access tailored to consumer
  health      Full diagnostic with isolation detection
  quality     Compute and display quality metrics
  repass      Manage re-pass queue
  adjacency   Rebuild source-source adjacency matrix
  export      Export manifest subset

Dependencies: Python 3.10+ (stdlib only; numpy optional for eigenvalues)
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_VERSION = '2.0.0'
DECAY = 0.5
ACTIVATION_THRESHOLD = 0.2
ITERATION_CAP = 3


# ---------------------------------------------------------------------------
# Concept key normalization — canonical source: schemas/normalize.py
# ---------------------------------------------------------------------------

try:
    # Import from shared schemas package (preferred)
    import importlib, sys as _sys
    _schema_dir = str(Path(__file__).resolve().parent.parent.parent / 'schemas')
    if _schema_dir not in _sys.path:
        _sys.path.insert(0, _schema_dir)
    from normalize import normalize_key
except (ImportError, Exception):
    # Fallback: inline copy for standalone invocation
    def normalize_key(text: str) -> str:
        """Normalize a concept name to a marker key (fallback)."""
        s = text.strip().lower()
        s = re.sub(r'\(.*?\)', '', s)
        s = re.sub(r'[^a-z0-9\s_]', '', s)
        s = re.sub(r'\s+', '_', s.strip())
        return s[:40]


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------

def create_empty_manifest(project: str = '') -> dict:
    """Create a fresh manifest structure."""
    today = date.today().isoformat()
    return {
        'version': MANIFEST_VERSION,
        'project': project,
        'created': today,
        'updated': today,
        'sources': {},
        'adjacency': {
            'matrix': {},
            'laplacian_eigenvalues': [],
            'clusters': [],
            'hub_scores': {},
        },
        'repass_queue': [],
        'stats': {
            'total_sources': 0,
            'total_concepts': 0,
            'total_cw_edges': 0,
            'total_forward_notes': 0,
            'mean_quality': 0.0,
            'isolation_count': 0,
        },
    }


def load_manifest(path: Path) -> dict:
    """Load manifest from JSON file."""
    if not path.exists():
        return create_empty_manifest()
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_manifest(manifest: dict, path: Path) -> None:
    """Save manifest to JSON file."""
    manifest['updated'] = date.today().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Alpha index parsing
# ---------------------------------------------------------------------------

def load_alpha_index(alpha_dir: Path) -> dict:
    """Load and return alpha/index.json."""
    index_path = alpha_dir / 'index.json'
    if not index_path.exists():
        return {}
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def extract_source_entries(alpha_index: dict) -> dict[str, list[dict]]:
    """Group alpha entries by source folder.

    Returns {source_folder: [{id, concept, distillation, marker, ...}, ...]}
    """
    entries_by_source = defaultdict(list)
    entries = alpha_index.get('entries', {})
    for entry_id, entry_data in entries.items():
        if not isinstance(entry_data, dict):
            continue
        if not entry_id.startswith('w:'):
            continue
        source = entry_data.get('source', '')
        if source.startswith('_'):
            continue  # Skip framework entries
        entries_by_source[source].append({
            'id': entry_id,
            'concept': entry_data.get('concept', ''),
            'distillation': entry_data.get('distillation', ''),
            'marker': entry_data.get('marker', ''),
            'maps_to': entry_data.get('maps_to', ''),
        })
    return dict(entries_by_source)


def extract_cw_graph(alpha_index: dict) -> dict[str, dict]:
    """Extract the convergence web graph section.

    Returns {cw_id: {thesis: w:X, athesis: w:Y}}
    """
    cw_graph = alpha_index.get('cw_graph', {})
    return cw_graph


def extract_cw_entries(alpha_index: dict) -> dict[str, dict]:
    """Extract convergence web entries from the entries section.

    Returns {cw_id: {source, concept, convergence_tag, ...}}
    """
    cw_entries = {}
    entries = alpha_index.get('entries', {})
    for entry_id, entry_data in entries.items():
        if not entry_id.startswith('cw:'):
            continue
        if isinstance(entry_data, dict):
            cw_entries[entry_id] = entry_data
    return cw_entries


def entry_id_to_source(entry_id: str, alpha_index: dict) -> str:
    """Resolve a w:N entry ID to its source folder."""
    entries = alpha_index.get('entries', {})
    entry = entries.get(entry_id, {})
    if isinstance(entry, dict):
        return entry.get('source', '')
    return ''


# ---------------------------------------------------------------------------
# Interpretation file parsing (reused from distill_recover_integration.py)
# ---------------------------------------------------------------------------

def parse_concept_table(text: str) -> list[dict]:
    """Extract concept mapping rows from interpretation tables."""
    mappings = []
    table_pattern = re.compile(
        r'^\|\s*([^\n|]+?)\s*\|\s*([^\n|]+?)\s*\|\s*(confirms?|extends?|challenges?|novel)\b',
        re.IGNORECASE | re.MULTILINE
    )
    for m in table_pattern.finditer(text):
        concept = m.group(1).strip().strip('*').strip()
        mapping = m.group(2).strip().strip('*').strip()
        relationship = m.group(3).strip().lower()
        # Skip header and separator rows
        if concept.lower() in ('concept', 'concept (from distillation)',
                                'source concept', '---', ''):
            continue
        if mapping.lower() in ('project mapping', 'mapping', '---', ''):
            continue
        if re.match(r'^[-|:\s]+$', concept):
            continue
        mappings.append({
            'concept': concept,
            'maps_to': mapping,
            'relationship': relationship,
        })
    return mappings


def parse_open_questions(text: str) -> list[str]:
    """Extract open questions from interpretation text."""
    questions = []
    sections = re.split(r'^##\s+', text, flags=re.MULTILINE)
    for section in sections:
        if not section.strip().startswith('Open Questions'):
            continue
        bullets = re.findall(r'[-*]\s+(.+?)(?:\n|$)', section)
        questions.extend(b.strip() for b in bullets if b.strip())
    return questions


def parse_forward_notes_from_text(text: str) -> list[str]:
    """Extract forward note numbers from interpretation text."""
    pattern = re.compile(r'§5\.(\d+)')
    numbers = set()
    for m in pattern.finditer(text):
        numbers.add(f"5.{m.group(1)}")
    return sorted(numbers, key=lambda x: int(x.split('.')[1]))


def extract_distillation_header(text: str) -> dict:
    """Extract header metadata from a distillation file."""
    header = {}
    register_m = re.search(r'>\s*Register:\s*(.+?)$', text, re.MULTILINE)
    if register_m:
        header['register'] = register_m.group(1).strip()
    source_type_m = re.search(r'>\s*Source type:\s*(.+?)$', text, re.MULTILINE)
    if source_type_m:
        header['source_type'] = source_type_m.group(1).strip()
    return header


# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------

def compute_concept_density(key_concepts: int, source_pages: int) -> float:
    """key_concepts / source_pages."""
    if source_pages <= 0:
        return 0.0
    return round(key_concepts / source_pages, 3)


def compute_coverage_ratio(mapped_concepts: int, key_concepts: int) -> float:
    """mapped_concepts / key_concepts."""
    if key_concepts <= 0:
        return 0.0
    return round(mapped_concepts / key_concepts, 3)


def compute_cross_ref_density(cw_edges: int, mapped_concepts: int) -> float:
    """cw_edges / mapped_concepts."""
    if mapped_concepts <= 0:
        return 0.0
    return round(cw_edges / mapped_concepts, 3)


def compute_forward_note_yield(forward_notes: int, mapped_concepts: int) -> float:
    """forward_notes / mapped_concepts."""
    if mapped_concepts <= 0:
        return 0.0
    return round(forward_notes / mapped_concepts, 3)


def compute_convergence_contribution(source_cw_edges: int, total_cw_edges: int) -> float:
    """source_cw_edges / total_cw_edges."""
    if total_cw_edges <= 0:
        return 0.0
    return round(source_cw_edges / total_cw_edges, 3)


def harmonic_mean(values: list[float]) -> float:
    """Compute harmonic mean of a list of values, skipping zeros."""
    positive = [v for v in values if v > 0]
    if not positive:
        return 0.0
    reciprocal_sum = sum(1.0 / v for v in positive)
    return round(len(positive) / reciprocal_sum, 3)


def compute_metrics(source_entry: dict, total_cw_edges: int,
                    source_pages: int = 0) -> dict:
    """Compute all quality metrics for a source entry."""
    concepts = source_entry.get('concepts', {})
    key_concepts = len(concepts)
    mapped_concepts = sum(1 for c in concepts.values()
                          if c.get('maps_to') and c.get('maps_to') != 'novel')
    # Count all mapped (including novel — they ARE mapped, just to new elements)
    mapped_concepts = len(concepts)
    cw_ids = source_entry.get('cw_ids', [])
    cw_edges = len(cw_ids)
    forward_notes = len(source_entry.get('forward_notes', []))

    cd = compute_concept_density(key_concepts, source_pages) if source_pages > 0 else 0.0
    cr = compute_coverage_ratio(mapped_concepts, key_concepts)
    xrd = compute_cross_ref_density(cw_edges, mapped_concepts)
    fny = compute_forward_note_yield(forward_notes, mapped_concepts)
    cc = compute_convergence_contribution(cw_edges, total_cw_edges)

    composite = harmonic_mean([v for v in [cd, cr, xrd, fny, cc] if v > 0])

    return {
        'concept_density': cd,
        'coverage_ratio': cr,
        'cross_ref_density': xrd,
        'forward_note_yield': fny,
        'convergence_contribution': cc,
        'composite_quality': composite,
    }


def format_quality_card(label: str, source_entry: dict) -> str:
    """Format a quality card for display."""
    m = source_entry.get('metrics', {})
    concepts = source_entry.get('concepts', {})
    cw_ids = source_entry.get('cw_ids', [])
    fwd = source_entry.get('forward_notes', [])
    oq = source_entry.get('open_questions', [])

    lines = [
        f"Quality Card: {label}",
        f"  concept_density:          {m.get('concept_density', 0):.3f}"
        f"  ({len(concepts)} concepts)",
        f"  coverage_ratio:           {m.get('coverage_ratio', 0):.3f}",
        f"  cross_ref_density:        {m.get('cross_ref_density', 0):.3f}"
        f"  ({len(cw_ids)} cw edges)",
        f"  forward_note_yield:       {m.get('forward_note_yield', 0):.3f}"
        f"  ({len(fwd)} notes)",
        f"  convergence_contribution: {m.get('convergence_contribution', 0):.3f}",
        f"  composite_quality:        {m.get('composite_quality', 0):.3f}"
        f"  [harmonic mean]",
        f"  iteration:                {source_entry.get('iteration', 1)}",
        f"  open_questions:           {len(oq)}",
    ]
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Information gain
# ---------------------------------------------------------------------------

def compute_information_gain(concept_maps_to: str,
                             all_mappings: dict[str, int],
                             total_concepts: int) -> float:
    """Compute information gain for a concept mapping.

    IG = -log2(prior_frequency / total_concepts)
    Novel mappings (prior_frequency = 0) get maximum IG.
    """
    if total_concepts <= 0:
        return 0.0
    prior = all_mappings.get(concept_maps_to, 0)
    if prior <= 0:
        # Novel — return maximum IG (capped at log2(total_concepts))
        return round(math.log2(max(total_concepts, 2)), 3)
    ratio = prior / total_concepts
    if ratio >= 1.0:
        return 0.0
    return round(-math.log2(ratio), 3)


# ---------------------------------------------------------------------------
# Adjacency matrix & graph math
# ---------------------------------------------------------------------------

def build_adjacency_matrix(alpha_index: dict) -> dict[str, dict[str, int]]:
    """Build source-source adjacency matrix from cw_graph.

    Each cw entry links two w: entries. The w: entries belong to sources.
    Edge weight = count of cw entries connecting two sources.
    """
    cw_graph = extract_cw_graph(alpha_index)
    matrix = defaultdict(lambda: defaultdict(int))

    for cw_id, edge in cw_graph.items():
        if not isinstance(edge, dict):
            continue
        thesis_id = edge.get('thesis', '')
        athesis_id = edge.get('athesis', '')
        if not thesis_id or not athesis_id:
            continue

        source_a = entry_id_to_source(thesis_id, alpha_index)
        source_b = entry_id_to_source(athesis_id, alpha_index)

        if not source_a or not source_b:
            continue
        if source_a.startswith('_') or source_b.startswith('_'):
            continue
        if source_a == source_b:
            continue

        matrix[source_a][source_b] += 1
        matrix[source_b][source_a] += 1

    # Convert to regular dicts
    return {k: dict(v) for k, v in matrix.items()}


def compute_degree(matrix: dict[str, dict[str, int]]) -> dict[str, int]:
    """Compute degree (sum of edge weights) for each source."""
    degrees = {}
    for source, neighbors in matrix.items():
        degrees[source] = sum(neighbors.values())
    return degrees


def compute_hub_scores(degrees: dict[str, int]) -> dict[str, float]:
    """Normalize degrees to 0-1 hub scores."""
    if not degrees:
        return {}
    max_degree = max(degrees.values())
    if max_degree <= 0:
        return {s: 0.0 for s in degrees}
    return {s: round(d / max_degree, 3) for s, d in degrees.items()}


def compute_clustering_coefficient(source: str,
                                    matrix: dict[str, dict[str, int]]) -> float:
    """Compute clustering coefficient for a source.

    C_i = 2 * E_i / (k_i * (k_i - 1))
    where k_i = degree, E_i = edges between neighbors.
    """
    neighbors = set(matrix.get(source, {}).keys())
    k = len(neighbors)
    if k < 2:
        return 0.0

    edges_between_neighbors = 0
    neighbor_list = list(neighbors)
    for i in range(len(neighbor_list)):
        for j in range(i + 1, len(neighbor_list)):
            n1, n2 = neighbor_list[i], neighbor_list[j]
            if n2 in matrix.get(n1, {}):
                edges_between_neighbors += 1

    return round(2.0 * edges_between_neighbors / (k * (k - 1)), 3)


def find_isolated_sources(all_sources: set[str],
                           matrix: dict[str, dict[str, int]]) -> list[str]:
    """Find sources with no convergence web connections."""
    connected = set(matrix.keys())
    return sorted(all_sources - connected)


def compute_laplacian_eigenvalues(matrix: dict[str, dict[str, int]],
                                   sources: list[str]) -> list[float]:
    """Compute eigenvalues of the graph Laplacian L = D - A.

    Requires numpy. Returns empty list if numpy unavailable.
    """
    try:
        import numpy as np
    except ImportError:
        return []

    n = len(sources)
    if n < 2:
        return []

    source_idx = {s: i for i, s in enumerate(sources)}
    A = np.zeros((n, n))
    for src, neighbors in matrix.items():
        if src not in source_idx:
            continue
        i = source_idx[src]
        for neighbor, weight in neighbors.items():
            if neighbor not in source_idx:
                continue
            j = source_idx[neighbor]
            A[i, j] = weight

    D = np.diag(A.sum(axis=1))
    L = D - A
    eigenvalues = np.linalg.eigvalsh(L)
    return [round(float(v), 6) for v in sorted(eigenvalues)]


# ---------------------------------------------------------------------------
# Spreading activation
# ---------------------------------------------------------------------------

def spreading_activation(source: str,
                          matrix: dict[str, dict[str, int]],
                          decay: float = DECAY,
                          threshold: float = ACTIVATION_THRESHOLD) -> dict[str, float]:
    """Propagate activation from a source through the adjacency graph.

    Returns {source: activation_level} for sources above threshold.
    """
    activations = {source: 1.0}
    visited = {source}

    # BFS with decay
    frontier = [(source, 1.0)]
    while frontier:
        next_frontier = []
        for current, current_activation in frontier:
            neighbors = matrix.get(current, {})
            for neighbor, weight in neighbors.items():
                if neighbor in visited:
                    continue
                # Normalize weight: edge_weight / max_possible
                max_weight = max(neighbors.values()) if neighbors else 1
                norm_weight = weight / max_weight if max_weight > 0 else 0
                new_activation = current_activation * decay * norm_weight
                if new_activation >= threshold:
                    activations[neighbor] = max(
                        activations.get(neighbor, 0), new_activation
                    )
                    next_frontier.append((neighbor, new_activation))
                    visited.add(neighbor)
        frontier = next_frontier

    # Remove the source itself
    activations.pop(source, None)
    return activations


# ---------------------------------------------------------------------------
# Repass queue
# ---------------------------------------------------------------------------

def add_to_repass_queue(manifest: dict, target: str,
                        triggering_source: str, reason: str,
                        concepts: list[str],
                        activation: float = 0.0) -> None:
    """Add or merge into the repass queue."""
    queue = manifest.setdefault('repass_queue', [])

    # Check for existing entry for this target
    for entry in queue:
        if entry['target_source'] == target:
            # Polyvocal merge
            if triggering_source not in entry['triggering_sources']:
                entry['triggering_sources'].append(triggering_source)
            entry['concepts'] = sorted(set(entry['concepts'] + concepts))
            entry['activation_level'] = max(entry['activation_level'], activation)
            entry['reason'] += f'; {reason}'
            return

    # New entry
    queue.append({
        'target_source': target,
        'triggering_sources': [triggering_source],
        'reason': reason,
        'concepts': concepts,
        'activation_level': round(activation, 3),
        'added': date.today().isoformat(),
        'iteration': 0,
    })


def pop_repass_entry(manifest: dict, target: str) -> dict | None:
    """Remove and return a repass queue entry for a target source."""
    queue = manifest.get('repass_queue', [])
    for i, entry in enumerate(queue):
        if entry['target_source'] == target:
            return queue.pop(i)
    return None


def mark_converged(manifest: dict, target: str) -> bool:
    """Remove a target from the repass queue (converged)."""
    return pop_repass_entry(manifest, target) is not None


# ---------------------------------------------------------------------------
# Bootstrap (init command)
# ---------------------------------------------------------------------------

def bootstrap_source_entry(label: str,
                           alpha_entries: list[dict],
                           cw_ids: list[str],
                           forward_notes: list[str],
                           open_questions: list[str],
                           distillation_file: str = '',
                           interpretation_file: str = '',
                           header: dict | None = None) -> dict:
    """Build a source entry from component data."""
    concepts = {}
    for entry in alpha_entries:
        key = normalize_key(entry.get('concept', ''))
        if not key or key == '?':
            continue
        concepts[key] = {
            'maps_to': entry.get('maps_to', ''),
            'relationship': '',
            'alpha_id': entry.get('id', ''),
            'information_gain': 0.0,
        }

    return {
        'date_distilled': '',
        'source_type': (header or {}).get('source_type', ''),
        'extraction_route': '',
        'register': (header or {}).get('register', ''),
        'distillation_file': distillation_file,
        'interpretation_file': interpretation_file,
        'concepts': concepts,
        'forward_notes': forward_notes,
        'cw_ids': cw_ids,
        'metrics': {},
        'iteration': 1,
        'open_questions': open_questions,
        'resolved_by': [],
        'resolves': [],
    }


def cmd_init(args):
    """Bootstrap manifest from existing alpha/interpretations."""
    manifest_path = Path(args.manifest)
    alpha_dir = Path(args.alpha_dir) if args.alpha_dir else None
    interp_dir = Path(args.interp_dir) if args.interp_dir else None
    distill_dir = Path(args.distill_dir) if args.distill_dir else None
    fn_path = Path(args.forward_notes) if args.forward_notes else None

    manifest = create_empty_manifest(args.project or '')

    # Load alpha index
    alpha_index = load_alpha_index(alpha_dir) if alpha_dir else {}
    entries_by_source = extract_source_entries(alpha_index)
    cw_entries = extract_cw_entries(alpha_index)
    cw_graph = extract_cw_graph(alpha_index)

    # Map w: IDs to their source folders
    w_to_source = {}
    entries_section = alpha_index.get('entries', {})
    for eid, edata in entries_section.items():
        if eid.startswith('w:') and isinstance(edata, dict):
            w_to_source[eid] = edata.get('source', '')

    # Map cw: IDs to involved sources
    cw_to_sources = {}
    for cw_id, edge in cw_graph.items():
        if not isinstance(edge, dict):
            continue
        t = edge.get('thesis', '')
        a = edge.get('athesis', '')
        src_t = w_to_source.get(t, '')
        src_a = w_to_source.get(a, '')
        cw_to_sources[cw_id] = (src_t, src_a)

    # Load forward notes
    fn_registry = {}
    if fn_path and fn_path.exists():
        try:
            fn_data = json.loads(fn_path.read_text(encoding='utf-8'))
            fn_registry = fn_data.get('notes', {})
        except (json.JSONDecodeError, OSError):
            pass

    # Group forward notes by source
    fn_by_source = defaultdict(list)
    for note_id, note_data in fn_registry.items():
        source = note_data.get('source', '')
        if source:
            fn_by_source[source].append(note_id)

    # Parse interpretation files
    interp_data = {}
    if interp_dir and interp_dir.exists():
        for f in sorted(interp_dir.glob('*.md')):
            try:
                text = f.read_text(encoding='utf-8')
                interp_data[f.stem] = {
                    'mappings': parse_concept_table(text),
                    'open_questions': parse_open_questions(text),
                    'forward_notes': parse_forward_notes_from_text(text),
                }
            except OSError:
                continue

    # Build source entries from alpha sources
    sources_section = alpha_index.get('sources', {})
    all_source_folders = set()

    for folder, folder_data in sources_section.items():
        if folder.startswith('_'):
            continue
        if not isinstance(folder_data, dict):
            continue
        all_source_folders.add(folder)

        alpha_entries = []
        w_ids = folder_data.get('cross_source_ids', [])
        for wid in w_ids:
            entry = entries_section.get(wid, {})
            if isinstance(entry, dict):
                alpha_entries.append({**entry, 'id': wid})

        # Find cw: IDs involving this source
        source_cw_ids = []
        for cw_id, (src_t, src_a) in cw_to_sources.items():
            if folder in (src_t, src_a):
                source_cw_ids.append(cw_id)

        # Find forward notes for this source
        source_fn = fn_by_source.get(folder, [])
        # Also try matching interpretation labels
        for interp_label in interp_data:
            candidate = interp_label.lower().replace('_', '-')
            if candidate == folder or folder.startswith(candidate.split('-')[0]):
                source_fn.extend(fn_by_source.get(interp_label, []))

        # Find open questions from interpretation
        oqs = []
        for interp_label, idata in interp_data.items():
            candidate = interp_label.lower().replace('_', '-')
            if candidate == folder or folder.startswith(candidate.split('-')[0]):
                oqs = idata.get('open_questions', [])
                break

        entry = bootstrap_source_entry(
            label=folder,
            alpha_entries=alpha_entries,
            cw_ids=sorted(set(source_cw_ids)),
            forward_notes=sorted(set(source_fn)),
            open_questions=oqs,
        )
        manifest['sources'][folder] = entry

    # Build adjacency matrix
    matrix = build_adjacency_matrix(alpha_index)
    degrees = compute_degree(matrix)
    hub_scores = compute_hub_scores(degrees)
    isolated = find_isolated_sources(all_source_folders, matrix)

    manifest['adjacency']['matrix'] = matrix
    manifest['adjacency']['hub_scores'] = hub_scores
    manifest['adjacency']['clusters'] = []

    # Compute eigenvalues if numpy available
    source_list = sorted(all_source_folders)
    eigenvalues = compute_laplacian_eigenvalues(matrix, source_list)
    manifest['adjacency']['laplacian_eigenvalues'] = eigenvalues

    # Compute quality metrics
    total_cw = len(cw_graph)
    for label, source_entry in manifest['sources'].items():
        metrics = compute_metrics(source_entry, total_cw)
        source_entry['metrics'] = metrics

    # Compute information gain
    mapping_counts = defaultdict(int)
    total_concepts = 0
    for source_entry in manifest['sources'].values():
        for concept_data in source_entry.get('concepts', {}).values():
            maps_to = concept_data.get('maps_to', '')
            if maps_to:
                mapping_counts[maps_to] += 1
                total_concepts += 1

    for source_entry in manifest['sources'].values():
        for concept_data in source_entry.get('concepts', {}).values():
            maps_to = concept_data.get('maps_to', '')
            ig = compute_information_gain(maps_to, mapping_counts, total_concepts)
            concept_data['information_gain'] = ig

    # Update stats
    all_concepts = sum(len(s.get('concepts', {}))
                       for s in manifest['sources'].values())
    all_fn = sum(len(s.get('forward_notes', []))
                 for s in manifest['sources'].values())
    qualities = [s.get('metrics', {}).get('composite_quality', 0)
                 for s in manifest['sources'].values()]
    mean_q = sum(qualities) / len(qualities) if qualities else 0.0

    manifest['stats'] = {
        'total_sources': len(manifest['sources']),
        'total_concepts': all_concepts,
        'total_cw_edges': total_cw,
        'total_forward_notes': all_fn,
        'mean_quality': round(mean_q, 3),
        'isolation_count': len(isolated),
    }

    if args.dry_run:
        print(json.dumps({
            'status': 'dry_run',
            'total_sources': len(manifest['sources']),
            'total_concepts': all_concepts,
            'total_cw_edges': total_cw,
            'isolated_sources': isolated,
            'hub_sources': [s for s, h in hub_scores.items() if h > 0.5],
            'eigenvalues_available': len(eigenvalues) > 0,
        }, indent=2))
    else:
        save_manifest(manifest, manifest_path)
        print(f"Manifest initialized: {len(manifest['sources'])} sources, "
              f"{all_concepts} concepts, {total_cw} cw edges", file=sys.stderr)
        print(f"Isolated: {len(isolated)}, Hubs: "
              f"{sum(1 for h in hub_scores.values() if h > 0.5)}", file=sys.stderr)
        if eigenvalues:
            fiedler = eigenvalues[1] if len(eigenvalues) > 1 else 0
            print(f"Algebraic connectivity (Fiedler): {fiedler:.4f}", file=sys.stderr)
        else:
            print("Eigenvalue analysis: numpy not available", file=sys.stderr)
        print(f"Written to {manifest_path}", file=sys.stderr)

    return manifest


# ---------------------------------------------------------------------------
# Update command
# ---------------------------------------------------------------------------

def cmd_update(args):
    """Add/update a source entry after distillation."""
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    label = args.source_label
    alpha_dir = Path(args.alpha_dir) if args.alpha_dir else None
    interp_file = Path(args.interp_file) if args.interp_file else None
    fn_path = Path(args.forward_notes) if args.forward_notes else None

    # Parse interpretation file
    mappings = []
    open_questions = []
    forward_notes_in_text = []
    if interp_file and interp_file.exists():
        text = interp_file.read_text(encoding='utf-8')
        mappings = parse_concept_table(text)
        open_questions = parse_open_questions(text)
        forward_notes_in_text = parse_forward_notes_from_text(text)

    # Get alpha IDs if provided
    alpha_ids = args.alpha_ids.split(',') if args.alpha_ids else []
    cw_ids = args.cw_ids.split(',') if args.cw_ids else []

    # Build concepts from mappings
    concepts = {}
    for m in mappings:
        key = normalize_key(m['concept'])
        if not key:
            continue
        concepts[key] = {
            'maps_to': m['maps_to'],
            'relationship': m['relationship'],
            'alpha_id': '',
            'information_gain': 0.0,
        }

    # Match alpha IDs to concepts if alpha index available
    if alpha_dir:
        alpha_index = load_alpha_index(alpha_dir)
        entries_section = alpha_index.get('entries', {})
        for wid in alpha_ids:
            entry = entries_section.get(wid, {})
            if isinstance(entry, dict):
                concept = entry.get('concept', '')
                key = normalize_key(concept)
                if key in concepts:
                    concepts[key]['alpha_id'] = wid

    # Get or create source entry
    existing = manifest['sources'].get(label, {})
    iteration = existing.get('iteration', 0) + 1

    source_entry = {
        'date_distilled': date.today().isoformat(),
        'source_type': existing.get('source_type', ''),
        'extraction_route': existing.get('extraction_route', ''),
        'register': existing.get('register', ''),
        'distillation_file': existing.get('distillation_file', ''),
        'interpretation_file': str(interp_file) if interp_file else '',
        'concepts': concepts,
        'forward_notes': forward_notes_in_text,
        'cw_ids': cw_ids,
        'metrics': {},
        'iteration': iteration,
        'open_questions': open_questions,
        'resolved_by': existing.get('resolved_by', []),
        'resolves': existing.get('resolves', []),
    }

    # Compute metrics
    total_cw = manifest['stats'].get('total_cw_edges', 0)
    source_entry['metrics'] = compute_metrics(source_entry, total_cw)

    manifest['sources'][label] = source_entry

    # Check for repass triggers via spreading activation
    matrix = manifest['adjacency'].get('matrix', {})
    if matrix:
        activations = spreading_activation(label, matrix)
        for target, level in activations.items():
            if target in manifest['sources']:
                add_to_repass_queue(
                    manifest, target, label,
                    f"Updated source {label} triggered activation",
                    list(concepts.keys())[:5],
                    level,
                )

    # Recompute stats
    _recompute_stats(manifest)

    save_manifest(manifest, manifest_path)

    print(json.dumps({
        'status': 'updated',
        'source': label,
        'concepts': len(concepts),
        'cw_edges': len(cw_ids),
        'forward_notes': len(forward_notes_in_text),
        'composite_quality': source_entry['metrics'].get('composite_quality', 0),
        'repass_queue_depth': len(manifest.get('repass_queue', [])),
    }, indent=2))


# ---------------------------------------------------------------------------
# Query command
# ---------------------------------------------------------------------------

def cmd_query(args):
    """Polymorphic access tailored to consumer."""
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    consumer = args.consumer
    source = args.source

    if consumer == 'pass4':
        # Forward note next_number from forward_notes.json
        fn_path = Path(args.forward_notes) if args.forward_notes else None
        next_number = 83  # default
        if fn_path and fn_path.exists():
            try:
                fn_data = json.loads(fn_path.read_text(encoding='utf-8'))
                next_number = fn_data.get('next_number', 83)
            except (json.JSONDecodeError, OSError):
                pass

        # All existing concept mappings for collision check
        all_mappings = {}
        for label, se in manifest['sources'].items():
            for key, cdata in se.get('concepts', {}).items():
                all_mappings[key] = {
                    'source': label,
                    'maps_to': cdata.get('maps_to', ''),
                    'relationship': cdata.get('relationship', ''),
                }

        # Open questions from all sources
        all_oqs = {}
        for label, se in manifest['sources'].items():
            oqs = se.get('open_questions', [])
            if oqs:
                all_oqs[label] = oqs

        # Repass entries targeting current or related sources
        repass = manifest.get('repass_queue', [])

        result = {
            'consumer': 'pass4',
            'forward_note_next_number': next_number,
            'existing_mappings_count': len(all_mappings),
            'open_questions': all_oqs,
            'repass_queue_depth': len(repass),
        }

        if source:
            # Source-specific: show concepts already mapped
            source_entry = manifest['sources'].get(source, {})
            result['source_concepts'] = list(source_entry.get('concepts', {}).keys())

        print(json.dumps(result, indent=2))

    elif consumer == 'integrate':
        result = {
            'consumer': 'integrate',
            'total_sources': manifest['stats']['total_sources'],
            'total_cw_edges': manifest['stats']['total_cw_edges'],
        }
        if source and source in manifest['sources']:
            se = manifest['sources'][source]
            result['source'] = {
                'concepts': len(se.get('concepts', {})),
                'cw_ids': se.get('cw_ids', []),
                'metrics': se.get('metrics', {}),
                'iteration': se.get('iteration', 1),
            }
        print(json.dumps(result, indent=2))

    elif consumer == 'sigma':
        hub_scores = manifest['adjacency'].get('hub_scores', {})
        clusters = manifest['adjacency'].get('clusters', [])

        # Build inverted concept->source index
        concept_source_idx = defaultdict(list)
        for label, se in manifest['sources'].items():
            for key in se.get('concepts', {}):
                concept_source_idx[key].append(label)

        result = {
            'consumer': 'sigma',
            'hub_scores': hub_scores,
            'clusters': clusters,
            'concept_source_index_size': len(concept_source_idx),
        }
        if source:
            adj_row = manifest['adjacency'].get('matrix', {}).get(source, {})
            result['adjacency_row'] = adj_row
            result['hub_score'] = hub_scores.get(source, 0)

        print(json.dumps(result, indent=2))

    elif consumer == 'health':
        isolated = find_isolated_sources(
            set(manifest['sources'].keys()),
            manifest['adjacency'].get('matrix', {})
        )
        qualities = [s.get('metrics', {}).get('composite_quality', 0)
                      for s in manifest['sources'].values()]

        result = {
            'consumer': 'health',
            'stats': manifest['stats'],
            'isolated_sources': isolated,
            'repass_queue_depth': len(manifest.get('repass_queue', [])),
            'quality_distribution': {
                'min': min(qualities) if qualities else 0,
                'max': max(qualities) if qualities else 0,
                'mean': manifest['stats'].get('mean_quality', 0),
            },
        }
        print(json.dumps(result, indent=2))

    else:
        print(json.dumps({'error': f'Unknown consumer: {consumer}'}))


# ---------------------------------------------------------------------------
# Health command
# ---------------------------------------------------------------------------

def cmd_health(args):
    """Full diagnostic with isolation detection."""
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    sources = manifest.get('sources', {})
    stats = manifest.get('stats', {})
    matrix = manifest.get('adjacency', {}).get('matrix', {})
    hub_scores = manifest.get('adjacency', {}).get('hub_scores', {})
    eigenvalues = manifest.get('adjacency', {}).get('laplacian_eigenvalues', [])
    repass = manifest.get('repass_queue', [])

    isolated = find_isolated_sources(set(sources.keys()), matrix)

    lines = [
        "=" * 60,
        "DISTILLATION MANIFEST HEALTH REPORT",
        "=" * 60,
        "",
        f"Project:           {manifest.get('project', '(none)')}",
        f"Version:           {manifest.get('version', '?')}",
        f"Updated:           {manifest.get('updated', '?')}",
        "",
        f"Total sources:     {stats.get('total_sources', 0)}",
        f"Total concepts:    {stats.get('total_concepts', 0)}",
        f"Total cw edges:    {stats.get('total_cw_edges', 0)}",
        f"Total fwd notes:   {stats.get('total_forward_notes', 0)}",
        f"Mean quality:      {stats.get('mean_quality', 0):.3f}",
        "",
    ]

    # Hubs
    hubs = [(s, h) for s, h in hub_scores.items() if h > 0.5]
    if hubs:
        lines.append("--- CONVERGENCE HUBS ---")
        for s, h in sorted(hubs, key=lambda x: x[1], reverse=True):
            lines.append(f"  {h:.3f}  {s}")
    else:
        lines.append("--- No convergence hubs (hub_score > 0.5) ---")

    # Isolated
    lines.append("")
    if isolated:
        lines.append(f"--- ISOLATED SOURCES ({len(isolated)}) ---")
        for s in isolated:
            lines.append(f"  {s}")
    else:
        lines.append("--- No isolated sources ---")

    # Eigenvalues
    if eigenvalues:
        lines.append("")
        lines.append("--- GRAPH LAPLACIAN ---")
        fiedler = eigenvalues[1] if len(eigenvalues) > 1 else 0
        lines.append(f"  Algebraic connectivity (Fiedler): {fiedler:.4f}")
        lines.append(f"  Eigenvalue range: [{eigenvalues[0]:.4f}, {eigenvalues[-1]:.4f}]")
    else:
        lines.append("")
        lines.append("--- Eigenvalues: not computed (numpy unavailable or <2 sources) ---")

    # Quality distribution
    qualities = [(label, se.get('metrics', {}).get('composite_quality', 0))
                  for label, se in sources.items()]
    if qualities:
        qualities.sort(key=lambda x: x[1])
        lines.append("")
        lines.append("--- QUALITY DISTRIBUTION ---")
        lines.append(f"  Lowest:  {qualities[0][1]:.3f}  {qualities[0][0]}")
        lines.append(f"  Highest: {qualities[-1][1]:.3f}  {qualities[-1][0]}")
        low_q = [(l, q) for l, q in qualities if q < 0.20 and q > 0]
        if low_q:
            lines.append(f"  Below 0.20 threshold: {len(low_q)} sources")
            for l, q in low_q[:5]:
                lines.append(f"    {q:.3f}  {l}")

    # Repass queue
    lines.append("")
    if repass:
        lines.append(f"--- REPASS QUEUE ({len(repass)} entries) ---")
        for entry in repass:
            target = entry.get('target_source', '?')
            triggers = ', '.join(entry.get('triggering_sources', []))
            activation = entry.get('activation_level', 0)
            lines.append(f"  {target} (activation: {activation:.3f})")
            lines.append(f"    triggered by: {triggers}")
            lines.append(f"    concepts: {', '.join(entry.get('concepts', [])[:5])}")
    else:
        lines.append("--- Repass queue: empty ---")

    lines.append("")
    lines.append("=" * 60)
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Quality command
# ---------------------------------------------------------------------------

def cmd_quality(args):
    """Compute and display quality metrics."""
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    if args.source:
        # Single source
        se = manifest['sources'].get(args.source)
        if not se:
            print(json.dumps({'error': f'Source not found: {args.source}'}))
            return

        if args.format == 'card':
            print(format_quality_card(args.source, se))
        elif args.format == 'json':
            print(json.dumps(se.get('metrics', {}), indent=2))
        else:  # table
            m = se.get('metrics', {})
            print(f"{'Metric':<30} {'Value':>8}")
            print("-" * 40)
            for key, val in m.items():
                print(f"{key:<30} {val:>8.3f}")
    else:
        # All sources
        if args.format == 'json':
            result = {}
            for label, se in manifest['sources'].items():
                result[label] = se.get('metrics', {})
            print(json.dumps(result, indent=2))
        else:  # table
            print(f"{'Source':<40} {'Quality':>8} {'Concepts':>10} "
                  f"{'CW':>5} {'FN':>5}")
            print("-" * 70)
            entries = sorted(
                manifest['sources'].items(),
                key=lambda x: x[1].get('metrics', {}).get('composite_quality', 0),
                reverse=True
            )
            for label, se in entries:
                m = se.get('metrics', {})
                print(f"{label[:40]:<40} "
                      f"{m.get('composite_quality', 0):>8.3f} "
                      f"{len(se.get('concepts', {})):>10} "
                      f"{len(se.get('cw_ids', [])):>5} "
                      f"{len(se.get('forward_notes', [])):>5}")


# ---------------------------------------------------------------------------
# Repass command
# ---------------------------------------------------------------------------

def cmd_repass(args):
    """Manage re-pass queue."""
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    if args.add:
        concepts = args.concepts.split(',') if args.concepts else []
        add_to_repass_queue(
            manifest, args.source, args.trigger or 'manual',
            args.reason or 'Manual re-pass request',
            concepts,
            float(args.activation) if args.activation else 1.0,
        )
        save_manifest(manifest, manifest_path)
        print(json.dumps({
            'status': 'added',
            'target': args.source,
            'queue_depth': len(manifest['repass_queue']),
        }, indent=2))

    elif args.pop:
        entry = pop_repass_entry(manifest, args.source)
        if entry:
            save_manifest(manifest, manifest_path)
            print(json.dumps({
                'status': 'popped',
                'entry': entry,
                'queue_depth': len(manifest['repass_queue']),
            }, indent=2))
        else:
            print(json.dumps({'status': 'not_found', 'source': args.source}))

    elif args.clear:
        manifest['repass_queue'] = []
        save_manifest(manifest, manifest_path)
        print(json.dumps({'status': 'cleared'}))

    else:
        # List
        queue = manifest.get('repass_queue', [])
        if not queue:
            print("Repass queue is empty.")
        else:
            for i, entry in enumerate(queue):
                print(f"\n[{i+1}] Target: {entry['target_source']}")
                print(f"    Triggers: {', '.join(entry['triggering_sources'])}")
                print(f"    Activation: {entry['activation_level']:.3f}")
                print(f"    Concepts: {', '.join(entry['concepts'][:5])}")
                print(f"    Iteration: {entry['iteration']}")


# ---------------------------------------------------------------------------
# Adjacency command
# ---------------------------------------------------------------------------

def cmd_adjacency(args):
    """Rebuild source-source adjacency matrix and graph metrics."""
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    alpha_dir = Path(args.alpha_dir)
    alpha_index = load_alpha_index(alpha_dir)

    # Build matrix
    matrix = build_adjacency_matrix(alpha_index)
    degrees = compute_degree(matrix)
    hub_scores = compute_hub_scores(degrees)

    all_sources = set(manifest['sources'].keys())
    isolated = find_isolated_sources(all_sources, matrix)

    # Clustering coefficients
    clustering = {}
    for source in all_sources:
        if source in matrix:
            clustering[source] = compute_clustering_coefficient(source, matrix)

    # Eigenvalues
    source_list = sorted(all_sources)
    eigenvalues = compute_laplacian_eigenvalues(matrix, source_list)

    # Update manifest
    manifest['adjacency'] = {
        'matrix': matrix,
        'laplacian_eigenvalues': eigenvalues,
        'clusters': [],
        'hub_scores': hub_scores,
    }
    manifest['stats']['isolation_count'] = len(isolated)

    save_manifest(manifest, manifest_path)

    # Report
    lines = [
        f"Adjacency matrix rebuilt: {len(matrix)} connected sources",
        f"Hub scores: {sum(1 for h in hub_scores.values() if h > 0.5)} hubs",
        f"Isolated: {len(isolated)} sources",
    ]
    if eigenvalues and len(eigenvalues) > 1:
        lines.append(f"Fiedler value: {eigenvalues[1]:.4f}")
    if clustering:
        avg_cc = sum(clustering.values()) / len(clustering)
        lines.append(f"Avg clustering coefficient: {avg_cc:.3f}")
    print('\n'.join(lines))


# ---------------------------------------------------------------------------
# Export command
# ---------------------------------------------------------------------------

def cmd_export(args):
    """Export manifest subset for external tooling."""
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)

    fmt = args.format

    if fmt == 'json':
        print(json.dumps(manifest, indent=2))

    elif fmt == 'csv':
        # CSV export: one row per source
        print("source,concepts,cw_edges,forward_notes,composite_quality,hub_score,iteration")
        hub_scores = manifest['adjacency'].get('hub_scores', {})
        for label, se in sorted(manifest['sources'].items()):
            m = se.get('metrics', {})
            print(f"{label},{len(se.get('concepts', {}))},"
                  f"{len(se.get('cw_ids', []))},"
                  f"{len(se.get('forward_notes', []))},"
                  f"{m.get('composite_quality', 0):.3f},"
                  f"{hub_scores.get(label, 0):.3f},"
                  f"{se.get('iteration', 1)}")

    elif fmt == 'dot':
        # DOT graph export for visualization
        lines = ['digraph sources {', '  rankdir=LR;']
        matrix = manifest['adjacency'].get('matrix', {})
        seen_edges = set()
        for src, neighbors in matrix.items():
            for dst, weight in neighbors.items():
                edge_key = tuple(sorted([src, dst]))
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    src_safe = src.replace('-', '_')
                    dst_safe = dst.replace('-', '_')
                    lines.append(f'  {src_safe} -> {dst_safe} '
                                 f'[label="{weight}" dir="none"];')
        lines.append('}')
        print('\n'.join(lines))

    else:
        print(json.dumps({'error': f'Unknown format: {fmt}'}))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _recompute_stats(manifest: dict) -> None:
    """Recompute manifest stats from source entries."""
    sources = manifest.get('sources', {})
    all_concepts = sum(len(s.get('concepts', {})) for s in sources.values())
    all_fn = sum(len(s.get('forward_notes', [])) for s in sources.values())
    qualities = [s.get('metrics', {}).get('composite_quality', 0)
                 for s in sources.values()]
    mean_q = sum(qualities) / len(qualities) if qualities else 0.0

    matrix = manifest.get('adjacency', {}).get('matrix', {})
    isolated = find_isolated_sources(set(sources.keys()), matrix)

    manifest['stats'] = {
        'total_sources': len(sources),
        'total_concepts': all_concepts,
        'total_cw_edges': manifest['stats'].get('total_cw_edges', 0),
        'total_forward_notes': all_fn,
        'mean_quality': round(mean_q, 3),
        'isolation_count': len(isolated),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Distillation manifest engine (v2.0)')
    subparsers = parser.add_subparsers(dest='command')

    # init
    init_p = subparsers.add_parser('init', help='Bootstrap manifest')
    init_p.add_argument('--manifest', required=True,
                        help='Path for manifest.json output')
    init_p.add_argument('--alpha-dir', default=None,
                        help='Path to alpha directory')
    init_p.add_argument('--interp-dir', default=None,
                        help='Path to interpretations directory')
    init_p.add_argument('--distill-dir', default=None,
                        help='Path to distillations directory')
    init_p.add_argument('--forward-notes', default=None,
                        help='Path to forward_notes.json')
    init_p.add_argument('--project', default='', help='Project name')
    init_p.add_argument('--dry-run', action='store_true')

    # update
    update_p = subparsers.add_parser('update', help='Update source entry')
    update_p.add_argument('--manifest', required=True)
    update_p.add_argument('--source-label', required=True)
    update_p.add_argument('--interp-file', default=None)
    update_p.add_argument('--alpha-dir', default=None)
    update_p.add_argument('--alpha-ids', default=None,
                          help='Comma-separated w: IDs')
    update_p.add_argument('--cw-ids', default=None,
                          help='Comma-separated cw: IDs')
    update_p.add_argument('--forward-notes', default=None)

    # query
    query_p = subparsers.add_parser('query', help='Polymorphic query')
    query_p.add_argument('--manifest', required=True)
    query_p.add_argument('--consumer', required=True,
                         choices=['pass4', 'integrate', 'sigma', 'health'])
    query_p.add_argument('--source', default=None)
    query_p.add_argument('--forward-notes', default=None)

    # health
    health_p = subparsers.add_parser('health', help='Full diagnostic')
    health_p.add_argument('--manifest', required=True)
    health_p.add_argument('--verbose', action='store_true')

    # quality
    quality_p = subparsers.add_parser('quality', help='Quality metrics')
    quality_p.add_argument('--manifest', required=True)
    quality_p.add_argument('--source', default=None)
    quality_p.add_argument('--format', default='table',
                           choices=['table', 'json', 'card'])

    # repass
    repass_p = subparsers.add_parser('repass', help='Manage repass queue')
    repass_p.add_argument('--manifest', required=True)
    repass_p.add_argument('--add', action='store_true', help='Add entry')
    repass_p.add_argument('--pop', action='store_true', help='Pop entry')
    repass_p.add_argument('--clear', action='store_true', help='Clear queue')
    repass_p.add_argument('--source', default=None, help='Target source')
    repass_p.add_argument('--trigger', default=None, help='Triggering source')
    repass_p.add_argument('--reason', default=None)
    repass_p.add_argument('--concepts', default=None,
                          help='Comma-separated concept keys')
    repass_p.add_argument('--activation', default=None)

    # adjacency
    adj_p = subparsers.add_parser('adjacency', help='Rebuild adjacency')
    adj_p.add_argument('--manifest', required=True)
    adj_p.add_argument('--alpha-dir', required=True)

    # export
    export_p = subparsers.add_parser('export', help='Export manifest')
    export_p.add_argument('--manifest', required=True)
    export_p.add_argument('--format', required=True,
                          choices=['json', 'csv', 'dot'])

    args = parser.parse_args()

    commands = {
        'init': cmd_init,
        'update': cmd_update,
        'query': cmd_query,
        'health': cmd_health,
        'quality': cmd_quality,
        'repass': cmd_repass,
        'adjacency': cmd_adjacency,
        'export': cmd_export,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
