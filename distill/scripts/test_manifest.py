#!/usr/bin/env python3
"""Tests for distill_manifest.py — Distillation manifest engine.

Run: pytest test_manifest.py -v
"""
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Import from the manifest module
import distill_manifest as dm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / 'fixtures'


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test outputs."""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def minimal_manifest(tmp_dir):
    """Load the minimal fixture manifest into a temp dir."""
    src = FIXTURES_DIR / 'manifest_minimal.json'
    dst = tmp_dir / 'manifest.json'
    shutil.copy(src, dst)
    return dst


@pytest.fixture
def empty_manifest(tmp_dir):
    """Create an empty manifest in a temp dir."""
    manifest = dm.create_empty_manifest('test-project')
    path = tmp_dir / 'manifest.json'
    dm.save_manifest(manifest, path)
    return path


@pytest.fixture
def sample_manifest():
    """Return a loaded minimal manifest dict."""
    src = FIXTURES_DIR / 'manifest_minimal.json'
    return json.loads(src.read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# TestManifestIO
# ---------------------------------------------------------------------------

class TestManifestIO:
    """Test manifest read/write/schema operations."""

    def test_create_empty_manifest(self):
        m = dm.create_empty_manifest('my-project')
        assert m['version'] == '2.0.0'
        assert m['project'] == 'my-project'
        assert m['sources'] == {}
        assert m['repass_queue'] == []

    def test_save_and_load(self, tmp_dir):
        path = tmp_dir / 'test.json'
        m = dm.create_empty_manifest('roundtrip')
        m['sources']['src-1'] = {'concepts': {}, 'cw_ids': []}
        dm.save_manifest(m, path)

        loaded = dm.load_manifest(path)
        assert loaded['project'] == 'roundtrip'
        assert 'src-1' in loaded['sources']

    def test_load_missing_file(self, tmp_dir):
        path = tmp_dir / 'nonexistent.json'
        m = dm.load_manifest(path)
        assert m['version'] == '2.0.0'
        assert m['sources'] == {}

    def test_load_fixture(self, sample_manifest):
        assert sample_manifest['version'] == '2.0.0'
        assert len(sample_manifest['sources']) == 3
        assert 'source-alpha' in sample_manifest['sources']

    def test_save_creates_parent_dirs(self, tmp_dir):
        path = tmp_dir / 'deep' / 'nested' / 'manifest.json'
        m = dm.create_empty_manifest()
        dm.save_manifest(m, path)
        assert path.exists()

    def test_save_updates_timestamp(self, tmp_dir):
        path = tmp_dir / 'test.json'
        m = dm.create_empty_manifest()
        m['updated'] = '2020-01-01'
        dm.save_manifest(m, path)
        loaded = dm.load_manifest(path)
        assert loaded['updated'] != '2020-01-01'

    def test_version_preserved(self, minimal_manifest):
        m = dm.load_manifest(minimal_manifest)
        assert m['version'] == '2.0.0'

    def test_unicode_handling(self, tmp_dir):
        path = tmp_dir / 'unicode.json'
        m = dm.create_empty_manifest()
        m['sources']['test'] = {
            'concepts': {'wholeness_w': {'maps_to': 'coherence'}},
            'cw_ids': [],
        }
        dm.save_manifest(m, path)
        loaded = dm.load_manifest(path)
        assert 'wholeness_w' in loaded['sources']['test']['concepts']


# ---------------------------------------------------------------------------
# TestMetricsComputer
# ---------------------------------------------------------------------------

class TestMetricsComputer:
    """Test quality metric computation."""

    def test_concept_density(self):
        assert dm.compute_concept_density(10, 20) == 0.5
        assert dm.compute_concept_density(15, 18) == pytest.approx(0.833, abs=0.001)

    def test_concept_density_zero_pages(self):
        assert dm.compute_concept_density(10, 0) == 0.0

    def test_coverage_ratio(self):
        assert dm.compute_coverage_ratio(8, 10) == 0.8
        assert dm.compute_coverage_ratio(0, 10) == 0.0

    def test_coverage_ratio_zero_concepts(self):
        assert dm.compute_coverage_ratio(5, 0) == 0.0

    def test_cross_ref_density(self):
        assert dm.compute_cross_ref_density(5, 10) == 0.5

    def test_cross_ref_density_zero(self):
        assert dm.compute_cross_ref_density(5, 0) == 0.0

    def test_forward_note_yield(self):
        assert dm.compute_forward_note_yield(3, 11) == pytest.approx(0.273, abs=0.001)

    def test_convergence_contribution(self):
        assert dm.compute_convergence_contribution(5, 148) == pytest.approx(0.034, abs=0.001)

    def test_convergence_contribution_zero_total(self):
        assert dm.compute_convergence_contribution(5, 0) == 0.0

    def test_harmonic_mean_basic(self):
        # harmonic mean of [2, 3, 6] = 3 / (1/2 + 1/3 + 1/6) = 3/1 = 3.0
        assert dm.harmonic_mean([2.0, 3.0, 6.0]) == 3.0

    def test_harmonic_mean_skips_zeros(self):
        # Zeros should be skipped
        result = dm.harmonic_mean([0.5, 0.0, 0.5])
        assert result == 0.5

    def test_harmonic_mean_all_zeros(self):
        assert dm.harmonic_mean([0.0, 0.0]) == 0.0

    def test_harmonic_mean_empty(self):
        assert dm.harmonic_mean([]) == 0.0

    def test_compute_metrics_full(self):
        source_entry = {
            'concepts': {
                'c1': {'maps_to': 'A', 'relationship': 'confirms'},
                'c2': {'maps_to': 'B', 'relationship': 'extends'},
            },
            'cw_ids': ['cw:1', 'cw:2'],
            'forward_notes': ['5.70'],
        }
        metrics = dm.compute_metrics(source_entry, total_cw_edges=10, source_pages=4)
        assert metrics['concept_density'] == 0.5
        assert metrics['coverage_ratio'] == 1.0
        assert metrics['cross_ref_density'] == 1.0
        assert metrics['forward_note_yield'] == 0.5
        assert metrics['convergence_contribution'] == 0.2
        assert metrics['composite_quality'] > 0


# ---------------------------------------------------------------------------
# TestInformationGain
# ---------------------------------------------------------------------------

class TestInformationGain:
    """Test information gain computation."""

    def test_novel_mapping(self):
        ig = dm.compute_information_gain('new_element', {}, 10)
        assert ig == pytest.approx(math.log2(10), abs=0.01)

    def test_common_mapping(self):
        mappings = {'element_a': 5}
        ig = dm.compute_information_gain('element_a', mappings, 10)
        # -log2(5/10) = -log2(0.5) = 1.0
        assert ig == 1.0

    def test_zero_total(self):
        assert dm.compute_information_gain('x', {}, 0) == 0.0

    def test_fully_common(self):
        # prior == total -> ratio >= 1.0 -> IG = 0
        assert dm.compute_information_gain('x', {'x': 10}, 10) == 0.0


# ---------------------------------------------------------------------------
# TestAdjacencyGraph
# ---------------------------------------------------------------------------

class TestAdjacencyGraph:
    """Test adjacency matrix and graph math."""

    def test_build_adjacency_from_sample(self, sample_manifest):
        matrix = sample_manifest['adjacency']['matrix']
        assert 'source-alpha' in matrix
        assert matrix['source-alpha']['source-beta'] == 2

    def test_compute_degree(self):
        matrix = {
            'A': {'B': 3, 'C': 1},
            'B': {'A': 3},
            'C': {'A': 1},
        }
        degrees = dm.compute_degree(matrix)
        assert degrees['A'] == 4
        assert degrees['B'] == 3
        assert degrees['C'] == 1

    def test_hub_scores(self):
        degrees = {'A': 10, 'B': 5, 'C': 2}
        hubs = dm.compute_hub_scores(degrees)
        assert hubs['A'] == 1.0
        assert hubs['B'] == 0.5
        assert hubs['C'] == 0.2

    def test_hub_scores_empty(self):
        assert dm.compute_hub_scores({}) == {}

    def test_clustering_coefficient_triangle(self):
        # Complete triangle: all neighbors connected
        matrix = {
            'A': {'B': 1, 'C': 1},
            'B': {'A': 1, 'C': 1},
            'C': {'A': 1, 'B': 1},
        }
        cc = dm.compute_clustering_coefficient('A', matrix)
        assert cc == 1.0

    def test_clustering_coefficient_star(self):
        # Star: A connects to B,C,D but B,C,D not connected to each other
        matrix = {
            'A': {'B': 1, 'C': 1, 'D': 1},
            'B': {'A': 1},
            'C': {'A': 1},
            'D': {'A': 1},
        }
        cc = dm.compute_clustering_coefficient('A', matrix)
        assert cc == 0.0

    def test_clustering_coefficient_single_neighbor(self):
        matrix = {'A': {'B': 1}, 'B': {'A': 1}}
        cc = dm.compute_clustering_coefficient('A', matrix)
        assert cc == 0.0  # Need at least 2 neighbors

    def test_find_isolated_sources(self):
        all_sources = {'A', 'B', 'C', 'D'}
        matrix = {'A': {'B': 1}, 'B': {'A': 1}}
        isolated = dm.find_isolated_sources(all_sources, matrix)
        assert sorted(isolated) == ['C', 'D']

    def test_find_isolated_no_isolation(self):
        all_sources = {'A', 'B'}
        matrix = {'A': {'B': 1}, 'B': {'A': 1}}
        isolated = dm.find_isolated_sources(all_sources, matrix)
        assert isolated == []

    def test_laplacian_eigenvalues_without_numpy(self):
        # This test checks graceful degradation
        # If numpy is available, it returns values; if not, returns []
        matrix = {'A': {'B': 1}, 'B': {'A': 1}}
        eigenvalues = dm.compute_laplacian_eigenvalues(matrix, ['A', 'B'])
        if eigenvalues:
            # Should have 2 eigenvalues: 0 and 2
            assert len(eigenvalues) == 2
            assert eigenvalues[0] == pytest.approx(0.0, abs=0.01)
            assert eigenvalues[1] == pytest.approx(2.0, abs=0.01)
        # If numpy not available, empty list is fine


# ---------------------------------------------------------------------------
# TestSpreadingActivation
# ---------------------------------------------------------------------------

class TestSpreadingActivation:
    """Test spreading activation on the source graph."""

    def test_basic_propagation(self):
        matrix = {
            'A': {'B': 2, 'C': 1},
            'B': {'A': 2, 'D': 1},
            'C': {'A': 1},
            'D': {'B': 1},
        }
        activations = dm.spreading_activation('A', matrix, decay=0.5, threshold=0.1)
        assert 'B' in activations
        assert 'C' in activations
        # B should have higher activation than C (weight 2 vs 1)
        assert activations['B'] >= activations['C']

    def test_decay_bounds_propagation(self):
        # Linear chain: A-B-C-D-E
        matrix = {
            'A': {'B': 1}, 'B': {'A': 1, 'C': 1},
            'C': {'B': 1, 'D': 1}, 'D': {'C': 1, 'E': 1},
            'E': {'D': 1},
        }
        activations = dm.spreading_activation('A', matrix, decay=0.5, threshold=0.2)
        # B gets 0.5, C gets 0.25, D gets 0.125 (below threshold)
        assert 'B' in activations
        assert 'C' in activations
        assert 'D' not in activations  # Below threshold

    def test_disconnected_component(self):
        matrix = {
            'A': {'B': 1},
            'B': {'A': 1},
            # C is disconnected
        }
        activations = dm.spreading_activation('A', matrix, decay=0.5, threshold=0.1)
        assert 'B' in activations
        assert 'C' not in activations

    def test_source_excluded_from_result(self):
        matrix = {'A': {'B': 1}, 'B': {'A': 1}}
        activations = dm.spreading_activation('A', matrix)
        assert 'A' not in activations


# ---------------------------------------------------------------------------
# TestRepassQueue
# ---------------------------------------------------------------------------

class TestRepassQueue:
    """Test repass queue management."""

    def test_add_new_entry(self):
        manifest = dm.create_empty_manifest()
        dm.add_to_repass_queue(
            manifest, 'target-src', 'trigger-src',
            'test reason', ['concept_a'], 0.5
        )
        assert len(manifest['repass_queue']) == 1
        entry = manifest['repass_queue'][0]
        assert entry['target_source'] == 'target-src'
        assert entry['triggering_sources'] == ['trigger-src']
        assert entry['activation_level'] == 0.5

    def test_polyvocal_merge(self):
        manifest = dm.create_empty_manifest()
        dm.add_to_repass_queue(
            manifest, 'target', 'src-1', 'reason 1', ['c1'], 0.3
        )
        dm.add_to_repass_queue(
            manifest, 'target', 'src-2', 'reason 2', ['c2'], 0.6
        )
        assert len(manifest['repass_queue']) == 1
        entry = manifest['repass_queue'][0]
        assert 'src-1' in entry['triggering_sources']
        assert 'src-2' in entry['triggering_sources']
        assert 'c1' in entry['concepts']
        assert 'c2' in entry['concepts']
        assert entry['activation_level'] == 0.6  # max

    def test_polyvocal_no_duplicate_trigger(self):
        manifest = dm.create_empty_manifest()
        dm.add_to_repass_queue(manifest, 'target', 'src-1', 'r1', ['c1'], 0.3)
        dm.add_to_repass_queue(manifest, 'target', 'src-1', 'r2', ['c2'], 0.5)
        entry = manifest['repass_queue'][0]
        assert entry['triggering_sources'].count('src-1') == 1

    def test_pop_entry(self):
        manifest = dm.create_empty_manifest()
        dm.add_to_repass_queue(manifest, 'target', 'src', 'r', ['c'], 0.5)
        entry = dm.pop_repass_entry(manifest, 'target')
        assert entry is not None
        assert entry['target_source'] == 'target'
        assert len(manifest['repass_queue']) == 0

    def test_pop_missing(self):
        manifest = dm.create_empty_manifest()
        entry = dm.pop_repass_entry(manifest, 'nonexistent')
        assert entry is None

    def test_mark_converged(self):
        manifest = dm.create_empty_manifest()
        dm.add_to_repass_queue(manifest, 'target', 'src', 'r', ['c'], 0.5)
        result = dm.mark_converged(manifest, 'target')
        assert result is True
        assert len(manifest['repass_queue']) == 0

    def test_bounded_iteration_tracking(self):
        manifest = dm.create_empty_manifest()
        dm.add_to_repass_queue(manifest, 'target', 'src', 'r', ['c'], 0.5)
        entry = manifest['repass_queue'][0]
        assert entry['iteration'] == 0

    def test_multiple_targets(self):
        manifest = dm.create_empty_manifest()
        dm.add_to_repass_queue(manifest, 'target-1', 'src', 'r1', ['c1'], 0.5)
        dm.add_to_repass_queue(manifest, 'target-2', 'src', 'r2', ['c2'], 0.3)
        assert len(manifest['repass_queue']) == 2
        dm.pop_repass_entry(manifest, 'target-1')
        assert len(manifest['repass_queue']) == 1
        assert manifest['repass_queue'][0]['target_source'] == 'target-2'


# ---------------------------------------------------------------------------
# TestBootstrap
# ---------------------------------------------------------------------------

class TestBootstrap:
    """Test manifest bootstrap from existing data."""

    def test_bootstrap_source_entry(self):
        alpha_entries = [
            {'id': 'w:1', 'concept': 'Test Concept', 'maps_to': 'framework_x'},
            {'id': 'w:2', 'concept': 'Another (parenthetical)', 'maps_to': 'y'},
        ]
        entry = dm.bootstrap_source_entry(
            label='test-source',
            alpha_entries=alpha_entries,
            cw_ids=['cw:1'],
            forward_notes=['5.70'],
            open_questions=['Is this real?'],
        )
        assert 'test_concept' in entry['concepts']
        assert 'another' in entry['concepts']
        assert entry['concepts']['test_concept']['alpha_id'] == 'w:1'
        assert entry['cw_ids'] == ['cw:1']
        assert entry['forward_notes'] == ['5.70']
        assert len(entry['open_questions']) == 1

    def test_bootstrap_skips_unknown_concept(self):
        alpha_entries = [
            {'id': 'w:1', 'concept': '?', 'maps_to': ''},
        ]
        entry = dm.bootstrap_source_entry(
            label='test', alpha_entries=alpha_entries,
            cw_ids=[], forward_notes=[], open_questions=[],
        )
        assert '?' not in entry['concepts']
        assert len(entry['concepts']) == 0

    def test_bootstrap_empty(self):
        entry = dm.bootstrap_source_entry(
            label='empty', alpha_entries=[],
            cw_ids=[], forward_notes=[], open_questions=[],
        )
        assert entry['concepts'] == {}
        assert entry['iteration'] == 1

    def test_normalize_key(self):
        # Parentheticals are stripped, so (W) disappears
        assert dm.normalize_key('Wholeness (W)') == 'wholeness'
        assert dm.normalize_key('Cross-metathesis') == 'crossmetathesis'
        assert dm.normalize_key('Degrees of life') == 'degrees_of_life'
        assert dm.normalize_key('A' * 50) == 'a' * 40  # truncation


# ---------------------------------------------------------------------------
# TestInterpretationParsing
# ---------------------------------------------------------------------------

class TestInterpretationParsing:
    """Test interpretation file parsing functions."""

    def test_parse_concept_table(self):
        text = """## Project Significance

| Concept (from distillation) | Project Mapping | Relationship |
|---|---|---|
| Wholeness | system coherence | confirms |
| Centers | agent nodes | extends |
| Degrees of life | vitality metric | novel |
"""
        mappings = dm.parse_concept_table(text)
        assert len(mappings) == 3
        assert mappings[0]['concept'] == 'Wholeness'
        assert mappings[0]['maps_to'] == 'system coherence'
        assert mappings[0]['relationship'] == 'confirms'
        assert mappings[2]['relationship'] == 'novel'

    def test_parse_concept_table_skips_header(self):
        text = "| Concept | Project Mapping | Relationship |\n| --- | --- | --- |"
        mappings = dm.parse_concept_table(text)
        assert len(mappings) == 0

    def test_parse_open_questions(self):
        text = """## Open Questions

- Does wholeness decompose into sub-wholenesses?
- How does the gradient relate to sigma?
"""
        questions = dm.parse_open_questions(text)
        assert len(questions) == 2
        assert 'wholeness' in questions[0].lower()

    def test_parse_forward_notes_from_text(self):
        text = """
Candidate forward notes:
- §5.75: Wholeness as geometric correlate
- §5.76: Centers as structural attractor nodes
Already discussed in §5.22.
"""
        notes = dm.parse_forward_notes_from_text(text)
        assert '5.75' in notes
        assert '5.76' in notes
        assert '5.22' in notes


# ---------------------------------------------------------------------------
# TestQualityCard
# ---------------------------------------------------------------------------

class TestQualityCard:
    """Test quality card formatting."""

    def test_format_quality_card(self, sample_manifest):
        source = sample_manifest['sources']['source-alpha']
        card = dm.format_quality_card('source-alpha', source)
        assert 'Quality Card: source-alpha' in card
        assert 'composite_quality' in card

    def test_format_quality_card_empty_metrics(self):
        source = {'concepts': {}, 'cw_ids': [], 'forward_notes': [],
                  'open_questions': [], 'metrics': {}, 'iteration': 1}
        card = dm.format_quality_card('empty-source', source)
        assert 'Quality Card: empty-source' in card


# ---------------------------------------------------------------------------
# TestRecomputeStats
# ---------------------------------------------------------------------------

class TestRecomputeStats:
    """Test stats recomputation."""

    def test_recompute_stats(self, sample_manifest):
        dm._recompute_stats(sample_manifest)
        assert sample_manifest['stats']['total_sources'] == 3
        assert sample_manifest['stats']['total_concepts'] == 4
        assert sample_manifest['stats']['isolation_count'] == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
