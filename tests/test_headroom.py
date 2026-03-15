# tests/test_headroom.py
"""Tests for headroom tier tracking (sigma_hook integration)."""

import json
import os

import pytest


class TestHeadroomTierFile:
    """Test the .sigma_headroom_tier file read/write pattern."""

    def test_no_file_returns_none(self, tmp_path):
        tier_path = tmp_path / '.sigma_headroom_tier'
        # No file → last tier is None (first time)
        assert not tier_path.exists()

    def test_write_and_read_tier(self, tmp_path):
        tier_path = tmp_path / '.sigma_headroom_tier'
        tier_path.write_text('watch')
        assert tier_path.read_text() == 'watch'

    def test_tier_crossing_detection(self, tmp_path):
        """Simulate the once-per-crossing pattern."""
        import importlib.util
        scripts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'plugin', 'scripts')
        _spec = importlib.util.spec_from_file_location(
            'telemetry', os.path.join(scripts_dir, 'telemetry.py'))
        telemetry = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(telemetry)

        tier_path = tmp_path / '.sigma_headroom_tier'

        # Simulate sequence: 60% → 72% → 78% → 88% → 90% → 95%
        percentages = [60, 72, 78, 88, 90, 95]
        expected_emissions = []  # (pct, tier) for each crossing

        last_tier = None
        for pct in percentages:
            current_tier = telemetry.tier_from_percentage(pct)
            if current_tier != last_tier and current_tier is not None:
                expected_emissions.append((pct, current_tier))
                last_tier = current_tier

        # Should emit: (72, watch), (88, warn), (95, critical)
        assert len(expected_emissions) == 3
        assert expected_emissions[0] == (72, 'watch')
        assert expected_emissions[1] == (88, 'warn')
        assert expected_emissions[2] == (95, 'critical')

    def test_no_emission_within_same_tier(self, tmp_path):
        """72% and 78% are both 'watch' — only one emission."""
        import importlib.util
        scripts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'plugin', 'scripts')
        _spec = importlib.util.spec_from_file_location(
            'telemetry', os.path.join(scripts_dir, 'telemetry.py'))
        telemetry = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(telemetry)

        emissions = []
        last_tier = 'watch'  # Already emitted watch
        for pct in [72, 75, 78, 80, 84]:
            tier = telemetry.tier_from_percentage(pct)
            if tier != last_tier and tier is not None:
                emissions.append(tier)
                last_tier = tier
        assert emissions == []  # No new crossings
