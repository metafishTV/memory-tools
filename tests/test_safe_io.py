# tests/test_safe_io.py
"""Tests for safe_io utility — atomic writes, validated reads, version checks."""

import importlib.util
import json
import os
import sys

import pytest

# Load safe_io via importlib
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'plugin', 'scripts'
)
_spec = importlib.util.spec_from_file_location(
    'safe_io', os.path.join(SCRIPTS_DIR, 'safe_io.py'))
safe_io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(safe_io)


# ---------------------------------------------------------------------------
# atomic_write_json
# ---------------------------------------------------------------------------

class TestAtomicWriteJson:
    def test_creates_file(self, tmp_path):
        path = str(tmp_path / 'test.json')
        safe_io.atomic_write_json(path, {'key': 'value'})
        with open(path) as f:
            assert json.load(f) == {'key': 'value'}

    def test_overwrites_existing(self, tmp_path):
        path = str(tmp_path / 'test.json')
        safe_io.atomic_write_json(path, {'v': 1})
        safe_io.atomic_write_json(path, {'v': 2})
        with open(path) as f:
            assert json.load(f) == {'v': 2}

    def test_no_temp_file_left_on_success(self, tmp_path):
        path = str(tmp_path / 'test.json')
        safe_io.atomic_write_json(path, {'ok': True})
        files = os.listdir(tmp_path)
        assert files == ['test.json']

    def test_no_partial_write_on_failure(self, tmp_path):
        path = str(tmp_path / 'test.json')
        safe_io.atomic_write_json(path, {'original': True})

        # Try to write non-serializable data — should fail
        with pytest.raises(TypeError):
            safe_io.atomic_write_json(path, {'bad': object()})

        # Original file should be intact
        with open(path) as f:
            assert json.load(f) == {'original': True}

        # No temp files left
        files = os.listdir(tmp_path)
        assert files == ['test.json']


# ---------------------------------------------------------------------------
# atomic_write_text
# ---------------------------------------------------------------------------

class TestAtomicWriteText:
    def test_creates_file(self, tmp_path):
        path = str(tmp_path / 'test.txt')
        safe_io.atomic_write_text(path, 'hello')
        assert open(path).read() == 'hello'

    def test_overwrites_existing(self, tmp_path):
        path = str(tmp_path / 'test.txt')
        safe_io.atomic_write_text(path, 'first')
        safe_io.atomic_write_text(path, 'second')
        assert open(path).read() == 'second'


# ---------------------------------------------------------------------------
# read_json
# ---------------------------------------------------------------------------

class TestReadJson:
    def test_reads_valid(self, tmp_path):
        path = tmp_path / 'test.json'
        path.write_text('{"key": "value"}')
        assert safe_io.read_json(str(path)) == {'key': 'value'}

    def test_returns_none_on_missing(self, tmp_path):
        assert safe_io.read_json(str(tmp_path / 'missing.json')) is None

    def test_raises_on_corrupt(self, tmp_path):
        path = tmp_path / 'bad.json'
        path.write_text('{truncated')
        with pytest.raises(json.JSONDecodeError):
            safe_io.read_json(str(path))

    def test_raises_on_empty(self, tmp_path):
        path = tmp_path / 'empty.json'
        path.write_text('')
        with pytest.raises(json.JSONDecodeError):
            safe_io.read_json(str(path))


# ---------------------------------------------------------------------------
# read_json_validated
# ---------------------------------------------------------------------------

class TestReadJsonValidated:
    def test_valid_with_required_keys(self, tmp_path):
        path = tmp_path / 'test.json'
        path.write_text('{"name": "foo", "count": 5}')
        result = safe_io.read_json_validated(str(path), required_keys=['name', 'count'])
        assert result == {'name': 'foo', 'count': 5}

    def test_missing_file_returns_none(self, tmp_path):
        result = safe_io.read_json_validated(str(tmp_path / 'missing.json'), required_keys=['x'])
        assert result is None

    def test_missing_required_key_raises(self, tmp_path):
        path = tmp_path / 'test.json'
        path.write_text('{"name": "foo"}')
        with pytest.raises(safe_io.HollowFileError, match='missing required keys'):
            safe_io.read_json_validated(str(path), required_keys=['name', 'count'])

    def test_hollow_key_raises(self, tmp_path):
        path = tmp_path / 'test.json'
        path.write_text('{"name": "foo", "items": {}}')
        with pytest.raises(safe_io.HollowFileError, match='hollow payload'):
            safe_io.read_json_validated(str(path), required_keys=['name', 'items'])

    def test_hollow_empty_string_raises(self, tmp_path):
        path = tmp_path / 'test.json'
        path.write_text('{"name": ""}')
        with pytest.raises(safe_io.HollowFileError, match='hollow payload'):
            safe_io.read_json_validated(str(path), required_keys=['name'])

    def test_hollow_null_raises(self, tmp_path):
        path = tmp_path / 'test.json'
        path.write_text('{"name": null}')
        with pytest.raises(safe_io.HollowFileError, match='hollow payload'):
            safe_io.read_json_validated(str(path), required_keys=['name'])

    def test_no_required_keys_passes(self, tmp_path):
        path = tmp_path / 'test.json'
        path.write_text('{"anything": true}')
        result = safe_io.read_json_validated(str(path))
        assert result == {'anything': True}

    def test_zero_is_not_hollow(self, tmp_path):
        """Zero is a legitimate value, not hollow."""
        path = tmp_path / 'test.json'
        path.write_text('{"count": 0}')
        result = safe_io.read_json_validated(str(path), required_keys=['count'])
        assert result == {'count': 0}

    def test_false_is_not_hollow(self, tmp_path):
        """False is a legitimate value, not hollow."""
        path = tmp_path / 'test.json'
        path.write_text('{"active": false}')
        result = safe_io.read_json_validated(str(path), required_keys=['active'])
        assert result == {'active': False}


# ---------------------------------------------------------------------------
# check_schema_version
# ---------------------------------------------------------------------------

class TestCheckSchemaVersion:
    def test_within_range(self):
        data = {'schema_version': 2}
        assert safe_io.check_schema_version(data, max_supported=2) == 2

    def test_below_range(self):
        data = {'schema_version': 1}
        assert safe_io.check_schema_version(data, max_supported=2) == 1

    def test_above_range_raises(self):
        data = {'schema_version': 3}
        with pytest.raises(safe_io.SchemaVersionError, match='schema_version 3 > 2'):
            safe_io.check_schema_version(data, max_supported=2)

    def test_missing_defaults_to_1(self):
        data = {'other': 'field'}
        assert safe_io.check_schema_version(data, max_supported=2) == 1

    def test_semver_string(self):
        data = {'schema_version': '2.0.0'}
        assert safe_io.check_schema_version(data, max_supported=2) == 2

    def test_semver_too_high(self):
        data = {'schema_version': '3.1.0'}
        with pytest.raises(safe_io.SchemaVersionError):
            safe_io.check_schema_version(data, max_supported=2)


# ---------------------------------------------------------------------------
# Marker TTL
# ---------------------------------------------------------------------------

class TestMarkerTTL:
    def test_fresh_marker(self, tmp_path):
        marker = tmp_path / '.test_marker'
        marker.write_text('active')
        assert safe_io.check_marker_ttl(str(marker), max_age_seconds=3600) is True

    def test_missing_marker(self, tmp_path):
        assert safe_io.check_marker_ttl(str(tmp_path / '.missing'), max_age_seconds=3600) is False

    def test_stale_marker_cleanup(self, tmp_path):
        marker = tmp_path / '.test_marker'
        marker.write_text('active')
        # Set mtime to 2 hours ago
        old_time = os.path.getmtime(str(marker)) - 7200
        os.utime(str(marker), (old_time, old_time))
        assert safe_io.cleanup_stale_marker(str(marker), max_age_seconds=3600) is True
        assert not marker.exists()

    def test_fresh_marker_not_cleaned(self, tmp_path):
        marker = tmp_path / '.test_marker'
        marker.write_text('active')
        assert safe_io.cleanup_stale_marker(str(marker), max_age_seconds=3600) is False
        assert marker.exists()


# ---------------------------------------------------------------------------
# Atomic counter
# ---------------------------------------------------------------------------

class TestAtomicCounter:
    def test_creates_counter(self, tmp_path):
        path = str(tmp_path / 'counter')
        result = safe_io.atomic_increment_counter(path)
        assert result == 1
        assert open(path).read() == '1'

    def test_increments_existing(self, tmp_path):
        path = str(tmp_path / 'counter')
        safe_io.atomic_increment_counter(path)
        safe_io.atomic_increment_counter(path)
        result = safe_io.atomic_increment_counter(path)
        assert result == 3

    def test_custom_amount(self, tmp_path):
        path = str(tmp_path / 'counter')
        result = safe_io.atomic_increment_counter(path, amount=5)
        assert result == 5


# ---------------------------------------------------------------------------
# Atomic read-modify-write
# ---------------------------------------------------------------------------

class TestAtomicReadModifyWrite:
    def test_modifies_existing(self, tmp_path):
        path = str(tmp_path / 'test.json')
        safe_io.atomic_write_json(path, {'count': 1})

        def increment(data):
            data['count'] += 1

        result = safe_io.atomic_read_modify_write_json(path, increment)
        assert result['count'] == 2
        with open(path) as f:
            assert json.load(f)['count'] == 2

    def test_missing_file_with_default(self, tmp_path):
        path = str(tmp_path / 'test.json')

        def init(data):
            data['initialized'] = True

        result = safe_io.atomic_read_modify_write_json(
            path, init, default=lambda: {'count': 0})
        assert result == {'count': 0, 'initialized': True}

    def test_missing_file_no_default(self, tmp_path):
        path = str(tmp_path / 'test.json')
        result = safe_io.atomic_read_modify_write_json(path, lambda d: d)
        assert result is None
