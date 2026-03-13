"""Tests for schemas/validate.py — schema validation tooling."""

import json
import os

import pytest

from validate import validate_data, validate_file, validate_all, validate_alpha_entries  # via conftest.py


# ---------------------------------------------------------------------------
# Alpha Entry Schema
# ---------------------------------------------------------------------------

class TestAlphaEntrySchema:
    """Test alpha-entry.schema.json validation."""

    def test_valid_entry(self):
        data = {
            "type": "cross_source",
            "source_folder": "sartre-early",
            "key": "Sartre:totalization",
            "maps_to": "recursive closure",
            "origin": "distill"
        }
        errors = validate_data('alpha-entry', data)
        assert errors == []

    def test_missing_required_field(self):
        data = {
            "type": "cross_source",
            "source_folder": "sartre-early"
            # missing 'key'
        }
        errors = validate_data('alpha-entry', data)
        assert any("'key' is a required property" in e for e in errors)

    def test_extra_fields_rejected(self):
        data = {
            "type": "cross_source",
            "source_folder": "test-source",
            "key": "Test:concept",
            "unexpected_field": "should fail"
        }
        errors = validate_data('alpha-entry', data)
        assert any("unexpected_field" in e or "Additional properties" in e for e in errors)

    def test_type_enum(self):
        data = {
            "type": "invalid_type",
            "source_folder": "test",
            "key": "Test:concept"
        }
        errors = validate_data('alpha-entry', data)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Convergence Web Schema
# ---------------------------------------------------------------------------

class TestConvergenceWebSchema:
    """Test convergence-web.schema.json validation."""

    def test_valid_cw_entry(self):
        data = {
            "type": "convergence_web",
            "source_folder": "sartre-early",
            "thesis": {"ref": "w:44", "label": "Sartre:totalization"},
            "athesis": {"ref": "w:45", "label": "Sartre:praxis"},
            "synthesis": "[complementarity] unified action through praxis",
            "metathesis": "practical ontology vs abstract totalization"
        }
        errors = validate_data('convergence-web', data)
        assert errors == []

    def test_missing_tetradic_field(self):
        data = {
            "type": "convergence_web",
            "source_folder": "test",
            "thesis": {"ref": "w:1", "label": "A:concept"},
            "athesis": {"ref": "w:2", "label": "B:concept"},
            "synthesis": "[complementarity] test"
            # missing metathesis
        }
        errors = validate_data('convergence-web', data)
        assert any("metathesis" in e for e in errors)

    def test_invalid_synthesis_tag(self):
        data = {
            "type": "convergence_web",
            "source_folder": "test",
            "thesis": {"ref": "w:1", "label": "A:x"},
            "athesis": {"ref": "w:2", "label": "B:y"},
            "synthesis": "[invalid_tag] some description",
            "metathesis": "test"
        }
        errors = validate_data('convergence-web', data)
        assert len(errors) > 0

    def test_valid_synthesis_tags(self):
        """All valid synthesis tags are accepted."""
        base = {
            "type": "convergence_web",
            "source_folder": "test",
            "thesis": {"ref": "w:1", "label": "A:x"},
            "athesis": {"ref": "w:2", "label": "B:y"},
            "metathesis": "test"
        }
        valid_tags = [
            "[complementarity]", "[independent_convergence]",
            "[genealogy]", "[elaboration]", "[tension]", "[wall]"
        ]
        for tag in valid_tags:
            data = {**base, "synthesis": f"{tag} description"}
            errors = validate_data('convergence-web', data)
            assert errors == [], f"Tag {tag} should be valid but got: {errors}"


# ---------------------------------------------------------------------------
# Alpha Index Schema
# ---------------------------------------------------------------------------

class TestAlphaIndexSchema:
    """Test alpha-index.schema.json validation."""

    def test_valid_index(self):
        data = {
            "schema_version": 1,
            "created": "2026-03-07",
            "last_updated": "2026-03-12",
            "rebuilt": True,
            "entries": {
                "w:1": {
                    "source": "test-source",
                    "file": "test-source/w001.md",
                    "concept": "test_concept",
                    "type": "cross_source"
                }
            },
            "sources": {
                "test-source": {
                    "folder": "test-source",
                    "cross_source_ids": ["w:1"],
                    "convergence_web_ids": [],
                    "entry_count": 1
                }
            },
            "concept_index": {"test_concept": ["w:1"]},
            "source_index": {"Test": ["w:1"]},
            "summary": {
                "total_cross_source": 1,
                "total_convergence_web": 0,
                "total_framework": 0,
                "total_sources": 1
            }
        }
        errors = validate_data('alpha-index', data)
        assert errors == []

    def test_framework_entry_no_type(self):
        """Framework entries may lack 'type' and 'file' — should still pass."""
        data = {
            "schema_version": 1,
            "last_updated": "2026-03-12",
            "entries": {
                "w:15": {
                    "source": "_framework",
                    "concept": "expression",
                    "group": "A",
                    "origin": "session"
                }
            },
            "sources": {
                "_framework": {
                    "folder": "_framework",
                    "framework": True,
                    "groups": ["A"],
                    "entry_count": 1
                }
            },
            "concept_index": {"expression": ["w:15"]},
            "source_index": {},
            "summary": {
                "total_cross_source": 0,
                "total_convergence_web": 0,
                "total_framework": 1,
                "total_sources": 1
            }
        }
        errors = validate_data('alpha-index', data)
        assert errors == []

    def test_convergence_tag_no_brackets(self):
        """convergence_tag values should NOT have brackets in stored format."""
        data = {
            "schema_version": 1,
            "last_updated": "2026-03-12",
            "entries": {
                "cw:1": {
                    "source": "test-source",
                    "file": "test-source/cw001.md",
                    "concept": "A:x x B:y",
                    "type": "convergence_web",
                    "convergence_tag": "independent_convergence",
                    "origin": "distill"
                }
            },
            "sources": {},
            "concept_index": {},
            "source_index": {},
            "summary": {
                "total_cross_source": 0,
                "total_convergence_web": 1,
                "total_framework": 0,
                "total_sources": 0
            }
        }
        errors = validate_data('alpha-index', data)
        assert errors == []

    def test_missing_summary(self):
        data = {
            "schema_version": 1,
            "last_updated": "2026-03-12",
            "entries": {},
            "sources": {},
            "concept_index": {},
            "source_index": {}
            # missing summary
        }
        errors = validate_data('alpha-index', data)
        assert any("summary" in e for e in errors)

    def test_malformed_entry(self):
        """Entries with wrong ID pattern fail."""
        data = {
            "schema_version": 1,
            "last_updated": "2026-03-12",
            "entries": {
                "bad_id": {"source": "x", "file": "x.md", "concept": "y", "type": "cross_source"}
            },
            "sources": {},
            "concept_index": {},
            "source_index": {},
            "summary": {
                "total_cross_source": 0,
                "total_convergence_web": 0,
                "total_framework": 0,
                "total_sources": 0
            }
        }
        errors = validate_data('alpha-index', data)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Manifest Source Schema
# ---------------------------------------------------------------------------

class TestManifestSourceSchema:
    """Test manifest-source.schema.json validation."""

    def test_valid_source(self):
        data = {
            "concepts": {
                "totalization": {
                    "maps_to": "recursive closure",
                    "relationship": "extends",
                    "alpha_id": "w:44"
                }
            },
            "forward_notes": ["§5.10"],
            "cw_ids": ["cw:1"],
            "metrics": {
                "concept_density": 3.5,
                "coverage_ratio": 0.8
            },
            "iteration": 1,
            "open_questions": [],
            "resolved_by": [],
            "resolves": []
        }
        errors = validate_data('manifest-source', data)
        assert errors == []

    def test_missing_concepts(self):
        data = {
            "forward_notes": [],
            "cw_ids": [],
            "metrics": {},
            "iteration": 1,
            "open_questions": [],
            "resolved_by": [],
            "resolves": []
        }
        errors = validate_data('manifest-source', data)
        assert any("concepts" in e for e in errors)

    def test_invalid_relationship(self):
        data = {
            "concepts": {
                "test": {
                    "maps_to": "something",
                    "relationship": "invalid_type"
                }
            },
            "forward_notes": [],
            "cw_ids": [],
            "metrics": {},
            "iteration": 1,
            "open_questions": [],
            "resolved_by": [],
            "resolves": []
        }
        errors = validate_data('manifest-source', data)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Forward Note Schema
# ---------------------------------------------------------------------------

class TestForwardNoteSchema:
    """Test forward-note.schema.json validation."""

    def test_valid_note(self):
        data = {
            "source": "DeLanda_AssemblageTheory_2016_Book",
            "description": "Explore parametrized assemblages for TAP",
            "status": "candidate",
            "date": "2026-03-12"
        }
        errors = validate_data('forward-note', data)
        assert errors == []

    def test_bookmarked_status_with_origin_and_xrefs(self):
        """Production notes have bookmarked status, origin, cross_references."""
        data = {
            "source": "design_doc",
            "description": "Shadow ticks / anapressive per-agent tracking",
            "status": "bookmarked",
            "date": "2026-02-26",
            "origin": "design_doc",
            "cross_references": [
                {
                    "source": "Cortes_etal_Paper",
                    "description": "References TAP equation",
                    "date": "2026-03-11"
                }
            ]
        }
        errors = validate_data('forward-note', data)
        assert errors == []

    def test_missing_required(self):
        data = {
            "source": "test",
            "description": "test"
            # missing status, date
        }
        errors = validate_data('forward-note', data)
        assert any("status" in e or "date" in e for e in errors)


# ---------------------------------------------------------------------------
# Hot Layer Schema
# ---------------------------------------------------------------------------

class TestHotLayerSchema:
    """Test hot-layer.schema.json validation."""

    def test_valid_hot_layer(self):
        data = {
            "schema_version": 2,
            "buffer_mode": "project",
            "scope": "full",
            "session_meta": {
                "date": "2026-03-12",
                "commit": "abc1234",
                "branch": "main"
            },
            "active_work": {
                "current_phase": "Testing",
                "completed_this_session": ["schema creation"],
                "in_progress": "Writing tests",
                "blocked_by": None,
                "next_action": "Run pytest"
            },
            "open_threads": [],
            "recent_decisions": [],
            "instance_notes": {
                "from": "instance-1",
                "to": "instance-2",
                "remarks": [],
                "open_questions": []
            },
            "memory_config": {
                "integration": "none",
                "path": None
            },
            "natural_summary": "Schema standardization session."
        }
        errors = validate_data('hot-layer', data)
        assert errors == []

    def test_missing_session_meta(self):
        data = {
            "schema_version": 2,
            "buffer_mode": "project",
            "scope": "full",
            # missing session_meta
            "active_work": {
                "current_phase": "x",
                "completed_this_session": [],
                "in_progress": None,
                "blocked_by": None,
                "next_action": None
            },
            "open_threads": [],
            "recent_decisions": [],
            "instance_notes": {"from": "a", "to": "b", "remarks": [], "open_questions": []},
            "memory_config": {"integration": "none", "path": None},
            "natural_summary": "test"
        }
        errors = validate_data('hot-layer', data)
        assert any("session_meta" in e for e in errors)

    def test_malformed_open_thread(self):
        data = {
            "schema_version": 2,
            "buffer_mode": "lite",
            "scope": "lite",
            "session_meta": {"date": "2026-03-12", "commit": "x", "branch": "main"},
            "active_work": {
                "current_phase": "x",
                "completed_this_session": [],
                "in_progress": None,
                "blocked_by": None,
                "next_action": None
            },
            "open_threads": [{"missing_thread_field": True}],
            "recent_decisions": [],
            "instance_notes": {"from": "a", "to": "b", "remarks": [], "open_questions": []},
            "memory_config": {"integration": "none", "path": None},
            "natural_summary": "test"
        }
        errors = validate_data('hot-layer', data)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Distill Stats Schema
# ---------------------------------------------------------------------------

class TestDistillStatsSchema:
    """Test distill-stats.schema.json validation."""

    def test_valid_stats(self):
        data = {
            "source_label": "Smith_Paper_2024_Paper",
            "source_type": "PDF",
            "extraction_date": "2026-03-12",
            "pages": {"total": 20, "text": 18, "tables": 2},
            "routes_used": ["A"]
        }
        errors = validate_data('distill-stats', data)
        assert errors == []

    def test_missing_source_label(self):
        data = {
            "source_type": "PDF",
            "extraction_date": "2026-03-12"
        }
        errors = validate_data('distill-stats', data)
        assert any("source_label" in e for e in errors)


# ---------------------------------------------------------------------------
# Validate All (integration test)
# ---------------------------------------------------------------------------

class TestValidateAll:
    """Test validate_all() against project directory structure."""

    def test_full_project_scan(self, tmp_path):
        """Valid project structure passes validation."""
        # Create minimal alpha index
        alpha_dir = tmp_path / '.claude' / 'buffer' / 'alpha'
        alpha_dir.mkdir(parents=True)
        index = {
            "schema_version": 2,
            "last_updated": "2026-03-12",
            "entries": {},
            "sources": {},
            "concept_index": {},
            "source_index": {},
            "summary": {
                "total_cross_source": 0,
                "total_convergence_web": 0,
                "total_framework": 0,
                "total_sources": 0
            }
        }
        (alpha_dir / 'index.json').write_text(json.dumps(index))

        results = validate_all(str(tmp_path))
        assert results['alpha-index'] == []

    def test_mixed_pass_fail(self, tmp_path):
        """Invalid alpha index reports errors, missing files report skip."""
        alpha_dir = tmp_path / '.claude' / 'buffer' / 'alpha'
        alpha_dir.mkdir(parents=True)
        bad_index = {"schema_version": 2, "entries": {}}  # missing fields
        (alpha_dir / 'index.json').write_text(json.dumps(bad_index))

        results = validate_all(str(tmp_path))
        assert len(results['alpha-index']) > 0  # errors
        assert 'not found' in results['manifest-sources'][0]  # skipped

    def test_empty_project(self, tmp_path):
        """Empty project directory skips all validations."""
        results = validate_all(str(tmp_path))
        for name, errs in results.items():
            assert 'not found' in errs[0] or 'skipped' in errs[0].lower()
