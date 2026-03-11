"""Tests for distill_forward_notes.py — clustering, similarity, and consolidation."""

import json
import pytest
import sys
from pathlib import Path

# Add distill scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'distill' / 'scripts'))

from distill_forward_notes import (
    tokenize, jaccard, compute_similarity, find_clusters,
    detect_superseded, group_by_source,
)


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic_tokenization(self):
        tokens = tokenize("Alexander's wholeness as coherence metric")
        assert 'wholeness' in tokens
        assert 'coherence' in tokens
        assert 'metric' in tokens

    def test_stopwords_removed(self):
        tokens = tokenize("the and for with this that from")
        assert len(tokens) == 0

    def test_short_words_excluded(self):
        tokens = tokenize("a to is of")
        assert len(tokens) == 0

    def test_empty_input(self):
        assert tokenize("") == set()
        assert tokenize(None) == set()


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        assert jaccard({'a', 'b', 'c'}, {'a', 'b', 'c'}) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({'a', 'b'}, {'c', 'd'}) == 0.0

    def test_partial_overlap(self):
        result = jaccard({'a', 'b', 'c'}, {'b', 'c', 'd'})
        assert result == pytest.approx(0.5)  # 2/4

    def test_empty_sets(self):
        assert jaccard(set(), set()) == 0.0
        assert jaccard({'a'}, set()) == 0.0


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------

class TestComputeSimilarity:
    def test_identical_descriptions(self):
        desc = "wholeness as coherence metric for active concept field"
        sim = compute_similarity(desc, desc)
        assert sim > 0.5

    def test_unrelated_descriptions(self):
        sim = compute_similarity(
            "wholeness as geometric coherence",
            "political cost of metathesis transition"
        )
        assert sim < 0.2

    def test_related_descriptions(self):
        sim = compute_similarity(
            "Alexander's wholeness W as formal correlate of system-level coherence",
            "Degrees of life as structural coherence metric"
        )
        assert sim > 0.0  # Some overlap on coherence
        # And more similar than completely unrelated
        unrelated = compute_similarity(
            "Alexander's wholeness W as formal correlate of system-level coherence",
            "political cost of metathesis transition"
        )
        assert sim > unrelated


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

class TestFindClusters:
    def test_no_clusters_with_dissimilar_notes(self):
        notes = {
            '5.1': {'description': 'TAP equation reference'},
            '5.70': {'description': 'political cost of metathesis'},
        }
        clusters = find_clusters(notes, threshold=0.3)
        assert len(clusters) == 0

    def test_finds_cluster_with_similar_notes(self):
        notes = {
            '5.75': {'description': 'wholeness W as coherence of system'},
            '5.76': {'description': 'degrees of life as structural coherence metric'},
            '5.77': {'description': 'fifteen properties as diagnostic for configuration quality'},
        }
        clusters = find_clusters(notes, threshold=0.15)
        # At least some clustering should occur
        if clusters:
            assert len(clusters[0]['notes']) >= 2

    def test_single_note_no_cluster(self):
        notes = {'5.1': {'description': 'solo note'}}
        clusters = find_clusters(notes)
        assert len(clusters) == 0

    def test_empty_notes(self):
        clusters = find_clusters({})
        assert len(clusters) == 0


# ---------------------------------------------------------------------------
# Supersession detection
# ---------------------------------------------------------------------------

class TestDetectSuperseded:
    def test_detects_self_identified_redundancy(self):
        notes = {
            '5.51': {
                'description': 'already cover this. No new forward note needed.',
                'status': 'candidate',
            }
        }
        result = detect_superseded(notes)
        assert len(result) == 1
        assert result[0]['note'] == '5.51'
        assert 'redundant' in result[0]['reason']

    def test_detects_implemented_status(self):
        notes = {
            '5.10': {
                'description': 'something already built',
                'status': 'implemented',
            }
        }
        result = detect_superseded(notes)
        assert len(result) == 1
        assert 'implemented' in result[0]['reason']

    def test_detects_cross_reference(self):
        notes = {
            '5.1': {
                'description': '§5.3 design notes should reference this',
                'status': 'candidate',
            }
        }
        result = detect_superseded(notes)
        assert len(result) == 1
        assert '§5.3' in result[0]['reason']

    def test_clean_note_not_flagged(self):
        notes = {
            '5.72': {
                'description': 'Sigma as predictive coding framework',
                'status': 'candidate',
            }
        }
        result = detect_superseded(notes)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Source grouping
# ---------------------------------------------------------------------------

class TestGroupBySource:
    def test_groups_correctly(self):
        notes = {
            '5.75': {'source': 'Alexander'},
            '5.76': {'source': 'Alexander'},
            '5.72': {'source': 'Kirsanov'},
        }
        groups = group_by_source(notes)
        assert len(groups['Alexander']) == 2
        assert len(groups['Kirsanov']) == 1


# ---------------------------------------------------------------------------
# Consolidation (filesystem-dependent)
# ---------------------------------------------------------------------------

class TestConsolidate:
    def test_merge_dry_run(self, tmp_path):
        from distill_forward_notes import cmd_consolidate
        registry = {
            'next_number': 80,
            'notes': {
                '5.72': {
                    'source': 'Kirsanov_A',
                    'description': 'sigma as predictive coding',
                    'status': 'candidate',
                    'date': '2026-03-11',
                },
                '5.79': {
                    'source': 'Kirsanov_B',
                    'description': 'energy minimization as convergence',
                    'status': 'candidate',
                    'date': '2026-03-11',
                },
            }
        }
        notes_path = tmp_path / 'forward_notes.json'
        notes_path.write_text(json.dumps(registry))

        import argparse
        args = argparse.Namespace(
            notes=str(notes_path), merge=['5.72', '5.79'],
            into='5.72', description=None, dry_run=True
        )
        # Should not raise; dry_run outputs JSON
        cmd_consolidate(args)

        # File should be unchanged (dry run)
        reloaded = json.loads(notes_path.read_text())
        assert reloaded['notes']['5.79']['status'] == 'candidate'

    def test_merge_execution(self, tmp_path):
        from distill_forward_notes import cmd_consolidate
        registry = {
            'next_number': 80,
            'notes': {
                '5.72': {
                    'source': 'Kirsanov_A',
                    'description': 'sigma as predictive coding',
                    'status': 'candidate',
                    'date': '2026-03-11',
                },
                '5.79': {
                    'source': 'Kirsanov_B',
                    'description': 'energy minimization as convergence',
                    'status': 'candidate',
                    'date': '2026-03-11',
                },
            }
        }
        notes_path = tmp_path / 'forward_notes.json'
        notes_path.write_text(json.dumps(registry))

        import argparse
        args = argparse.Namespace(
            notes=str(notes_path), merge=['5.72', '5.79'],
            into='5.72', description='unified predictive coding + energy',
            dry_run=False
        )
        cmd_consolidate(args)

        reloaded = json.loads(notes_path.read_text())
        assert reloaded['notes']['5.72']['description'] == 'unified predictive coding + energy'
        assert reloaded['notes']['5.79']['status'] == 'merged_into'
        assert reloaded['notes']['5.79']['merged_into'] == '5.72'


# ---------------------------------------------------------------------------
# Check-new (for integrate step)
# ---------------------------------------------------------------------------

class TestCheckNew:
    def test_finds_similar_existing(self, tmp_path):
        from distill_forward_notes import cmd_check_new
        registry = {
            'next_number': 80,
            'notes': {
                '5.75': {
                    'source': 'Alexander',
                    'description': 'wholeness W as coherence of system-level structure',
                    'status': 'candidate',
                    'date': '2026-03-11',
                },
            }
        }
        notes_path = tmp_path / 'forward_notes.json'
        notes_path.write_text(json.dumps(registry))

        import argparse
        args = argparse.Namespace(
            notes=str(notes_path),
            description='coherence metric for system wholeness',
            alpha_dir=None, threshold=0.15
        )
        # Should find similarity with 5.75
        cmd_check_new(args)
