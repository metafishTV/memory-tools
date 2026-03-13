"""Tests for redistill-changelog.schema.json validation."""

from validate import validate_data  # via conftest.py SCHEMAS_DIR path setup


class TestRedistillChangelog:
    """Test redistill-changelog.schema.json validation."""

    def test_valid_changelog(self):
        data = {
            "source_label": "DeLanda_AssemblageTheory_2016_Book",
            "redistill_date": "2026-03-12",
            "mode": "update",
            "iteration": 2,
            "previous": {
                "date": "2026-02-28",
                "concept_count": 7,
                "concept_keys": ["parametrized_assemblage", "coding", "territorialization"]
            },
            "current": {
                "concept_count": 10,
                "concept_keys": [
                    "parametrized_assemblage", "coding", "territorialization",
                    "three_lines", "counter_actualization", "co_actualization"
                ]
            },
            "diff": {
                "added": ["three_lines", "counter_actualization", "co_actualization"],
                "removed": [],
                "retained": ["parametrized_assemblage", "coding", "territorialization"],
                "modified": []
            },
            "alpha_changes": {
                "new_ids": ["w:471", "w:472", "w:473"],
                "updated_ids": [],
                "orphaned_ids": []
            }
        }
        errors = validate_data('redistill-changelog', data)
        assert errors == []

    def test_diff_computation_consistency(self):
        """Diff fields should be logically consistent (added + retained = current)."""
        data = {
            "source_label": "Test_Source",
            "redistill_date": "2026-03-12",
            "mode": "archive",
            "iteration": 3,
            "previous": {
                "date": "2026-03-01",
                "concept_count": 3,
                "concept_keys": ["a", "b", "c"]
            },
            "current": {
                "concept_count": 4,
                "concept_keys": ["a", "b", "d", "e"]
            },
            "diff": {
                "added": ["d", "e"],
                "removed": ["c"],
                "retained": ["a", "b"],
                "modified": []
            },
            "alpha_changes": {
                "new_ids": ["w:100", "w:101"],
                "updated_ids": [],
                "orphaned_ids": ["w:50"]
            }
        }
        errors = validate_data('redistill-changelog', data)
        assert errors == []

        # Verify logical consistency
        assert set(data['diff']['retained']) | set(data['diff']['added']) == set(data['current']['concept_keys'])
        assert set(data['diff']['retained']) | set(data['diff']['removed']) == set(data['previous']['concept_keys'])

    def test_empty_previous(self):
        """Edge case: previous has zero concepts (shouldn't happen, but validates)."""
        data = {
            "source_label": "Edge_Case",
            "redistill_date": "2026-03-12",
            "mode": "delete",
            "iteration": 2,
            "previous": {
                "date": "2026-01-01",
                "concept_count": 0,
                "concept_keys": []
            },
            "current": {
                "concept_count": 2,
                "concept_keys": ["new_a", "new_b"]
            },
            "diff": {
                "added": ["new_a", "new_b"],
                "removed": [],
                "retained": [],
                "modified": []
            },
            "alpha_changes": {
                "new_ids": ["w:1", "w:2"],
                "updated_ids": [],
                "orphaned_ids": []
            }
        }
        errors = validate_data('redistill-changelog', data)
        assert errors == []

    def test_iteration_must_be_at_least_2(self):
        """Iteration < 2 should fail (redistill implies iteration >= 2)."""
        data = {
            "source_label": "Test",
            "redistill_date": "2026-03-12",
            "mode": "update",
            "iteration": 1,  # invalid for redistill
            "previous": {"date": "2026-01-01", "concept_count": 0, "concept_keys": []},
            "current": {"concept_count": 0, "concept_keys": []},
            "diff": {"added": [], "removed": [], "retained": [], "modified": []},
            "alpha_changes": {"new_ids": [], "updated_ids": [], "orphaned_ids": []}
        }
        errors = validate_data('redistill-changelog', data)
        assert len(errors) > 0

    def test_missing_required_fields(self):
        """Missing top-level fields should fail."""
        data = {
            "source_label": "Test",
            "redistill_date": "2026-03-12"
            # missing mode, iteration, previous, current, diff, alpha_changes
        }
        errors = validate_data('redistill-changelog', data)
        assert len(errors) >= 4  # at least 4 missing required fields
