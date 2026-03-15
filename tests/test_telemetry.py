# tests/test_telemetry.py
"""Tests for telemetry utility — emit, tiers, cache ratio, once-per-crossing."""

import json
import os
import sys
import importlib.util
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Load telemetry module via importlib (same pattern as other buffer tests)
# ---------------------------------------------------------------------------

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'plugin', 'scripts'
)

_spec = importlib.util.spec_from_file_location(
    'telemetry', os.path.join(SCRIPTS_DIR, 'telemetry.py'))
telemetry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(telemetry)


# ---------------------------------------------------------------------------
# tier_from_percentage
# ---------------------------------------------------------------------------

class TestTierFromPercentage:
    def test_below_70_returns_none(self):
        assert telemetry.tier_from_percentage(0) is None
        assert telemetry.tier_from_percentage(50) is None
        assert telemetry.tier_from_percentage(69) is None

    def test_watch_tier(self):
        assert telemetry.tier_from_percentage(70) == 'watch'
        assert telemetry.tier_from_percentage(75) == 'watch'
        assert telemetry.tier_from_percentage(84) == 'watch'

    def test_warn_tier(self):
        assert telemetry.tier_from_percentage(85) == 'warn'
        assert telemetry.tier_from_percentage(90) == 'warn'
        assert telemetry.tier_from_percentage(92) == 'warn'

    def test_critical_tier(self):
        assert telemetry.tier_from_percentage(93) == 'critical'
        assert telemetry.tier_from_percentage(95) == 'critical'
        assert telemetry.tier_from_percentage(100) == 'critical'

    def test_exact_boundaries(self):
        """Boundaries use >= so exact values hit the higher tier."""
        assert telemetry.tier_from_percentage(70) == 'watch'
        assert telemetry.tier_from_percentage(85) == 'warn'
        assert telemetry.tier_from_percentage(93) == 'critical'


# ---------------------------------------------------------------------------
# cache_ratio
# ---------------------------------------------------------------------------

class TestCacheRatio:
    def test_normal_calculation(self):
        ratio = telemetry.cache_ratio(42, 50, 8)
        assert ratio == pytest.approx(0.42)

    def test_zero_division(self):
        assert telemetry.cache_ratio(0, 0, 0) == 0.0

    def test_all_cache_read(self):
        assert telemetry.cache_ratio(100, 0, 0) == pytest.approx(1.0)

    def test_no_cache_read(self):
        assert telemetry.cache_ratio(0, 50, 50) == 0.0


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

class TestEmit:
    def test_creates_file(self, tmp_path):
        telemetry.emit(str(tmp_path), {'event': 'test'})
        path = tmp_path / 'telemetry.jsonl'
        assert path.exists()
        entry = json.loads(path.read_text().strip())
        assert entry['event'] == 'test'
        assert 'ts' in entry

    def test_appends_not_overwrites(self, tmp_path):
        telemetry.emit(str(tmp_path), {'event': 'first'})
        telemetry.emit(str(tmp_path), {'event': 'second'})
        lines = (tmp_path / 'telemetry.jsonl').read_text().strip().split('\n')
        assert len(lines) == 2
        assert json.loads(lines[0])['event'] == 'first'
        assert json.loads(lines[1])['event'] == 'second'

    def test_auto_timestamps(self, tmp_path):
        telemetry.emit(str(tmp_path), {'event': 'check_ts'})
        entry = json.loads(
            (tmp_path / 'telemetry.jsonl').read_text().strip())
        ts = entry['ts']
        # Should be valid ISO 8601 — parse it
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None  # timezone-aware

    def test_fail_silent(self, tmp_path):
        """Unwritable path doesn't raise."""
        bad_dir = str(tmp_path / 'nonexistent' / 'deep' / 'path')
        # Should not raise
        telemetry.emit(bad_dir, {'event': 'should_not_crash'})


# ---------------------------------------------------------------------------
# Once-per-crossing logic (tested as tier transitions)
# ---------------------------------------------------------------------------

class TestOncePerCrossing:
    """Tests for the tier-crossing detection pattern used by sigma_hook.

    The actual 'last tier' tracking lives in sigma_hook, but we test the
    tier_from_percentage function's role in the pattern here.
    """

    def test_same_tier_twice(self):
        """Same percentage range should produce same tier (caller deduplicates)."""
        assert telemetry.tier_from_percentage(72) == telemetry.tier_from_percentage(78)

    def test_tier_upgrade_different(self):
        """Crossing from watch to warn produces different tier values."""
        tier_a = telemetry.tier_from_percentage(80)
        tier_b = telemetry.tier_from_percentage(90)
        assert tier_a != tier_b
        assert tier_a == 'watch'
        assert tier_b == 'warn'


# ---------------------------------------------------------------------------
# cmd_session_end
# ---------------------------------------------------------------------------

class TestSessionEnd:
    def test_session_end_with_events(self, tmp_path):
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        # Write some telemetry entries
        telemetry.emit(str(tmp_path), {
            'event': 'compact', 'context_pct': 93})
        telemetry.emit(str(tmp_path), {
            'event': 'headroom_warning', 'context_pct': 87, 'tier': 'warn'})
        telemetry.emit(str(tmp_path), {
            'event': 'headroom_warning', 'context_pct': 72, 'tier': 'watch'})
        telemetry.emit(str(tmp_path), {
            'event': 'compact', 'context_pct': 95})

        # Write .session_active
        sa_path = tmp_path / '.session_active'
        sa_path.write_text(json.dumps({'date': today, 'off_count': 2}))

        # Run session-end
        telemetry.cmd_session_end(str(tmp_path))

        # Read last line (the session_end event)
        lines = (tmp_path / 'telemetry.jsonl').read_text().strip().split('\n')
        end_event = json.loads(lines[-1])
        assert end_event['event'] == 'session_end'
        assert end_event['compactions'] == 2
        assert end_event['warnings_emitted'] == 2
        assert end_event['peak_context_pct'] == 95
        assert end_event['off_count'] == 2

    def test_session_end_no_prior_events(self, tmp_path):
        """Session end with no prior telemetry emits zeros."""
        telemetry.cmd_session_end(str(tmp_path))
        lines = (tmp_path / 'telemetry.jsonl').read_text().strip().split('\n')
        end_event = json.loads(lines[-1])
        assert end_event['event'] == 'session_end'
        assert end_event['compactions'] == 0
        assert end_event['warnings_emitted'] == 0
        assert end_event['peak_context_pct'] == 0
