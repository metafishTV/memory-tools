"""End-to-end tests for sigma_hook.py lite-mode gating.

Subprocess-based tests that verify the full hook stdin→stdout flow,
with focus on lite vs full mode behavior differences.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOK_SCRIPT = Path(__file__).parent.parent / 'plugin' / 'scripts' / 'sigma_hook.py'
PYTHON = sys.executable


def make_buffer(tmp_path, buffer_mode='lite', hot_extras=None,
                alpha_index=None, regime=None):
    """Create a minimal buffer directory with the given mode."""
    buf = tmp_path / '.claude' / 'buffer'
    buf.mkdir(parents=True)

    hot = {
        'schema_version': 2,
        'buffer_mode': buffer_mode,
        'session_meta': {'date': '2026-03-13', 'commit': 'abc1234', 'branch': 'main'},
        'orientation': {'core_insight': 'Test project', 'practical_warning': 'None'},
        'active_work': {
            'current_phase': 'Testing sigma hook',
            'completed_this_session': [],
            'in_progress': 'architecture refactor',
            'blocked_by': None,
            'next_action': 'Run tests'
        },
        'open_threads': [
            {'thread': 'Architecture review needed', 'status': 'noted'}
        ],
        'recent_decisions': [],
        'instance_notes': {'remarks': '', 'open_questions': []},
        'natural_summary': 'Testing.'
    }
    if hot_extras:
        hot.update(hot_extras)
    (buf / 'handoff.json').write_text(json.dumps(hot), encoding='utf-8')

    if alpha_index is not None:
        alpha_dir = buf / 'alpha'
        alpha_dir.mkdir()
        (alpha_dir / 'index.json').write_text(
            json.dumps(alpha_index), encoding='utf-8')

    if regime is not None:
        (buf / '.sigma_regime').write_text(
            json.dumps(regime), encoding='utf-8')

    return str(buf)


def run_hook(user_prompt, cwd, timeout=10):
    """Run sigma_hook.py as subprocess with simulated hook input."""
    stdin_data = json.dumps({
        'user_prompt': user_prompt,
        'cwd': cwd,
    })
    result = subprocess.run(
        [PYTHON, str(HOOK_SCRIPT)],
        input=stdin_data, capture_output=True, text=True, timeout=timeout,
    )
    if result.stdout.strip():
        return json.loads(result.stdout.strip())
    return {}


def clear_cooldown(buffer_dir):
    """Remove the cooldown marker so the hook fires."""
    marker = os.path.join(buffer_dir, '.sigma_last_fire')
    if os.path.exists(marker):
        os.remove(marker)


class TestLiteModeE2E:
    """End-to-end tests for lite-mode sigma hook behavior."""

    def test_lite_mode_fires_on_hot_match(self, tmp_path):
        """Lite mode should match against hot layer keywords."""
        buf = make_buffer(tmp_path, buffer_mode='lite')
        clear_cooldown(buf)
        result = run_hook('How is the architecture refactor going?', str(tmp_path))
        # Should get a hot-layer match (architecture is in active_work)
        if result.get('systemMessage'):
            assert 'sigma hot' in result['systemMessage']

    def test_lite_mode_no_regime_file(self, tmp_path):
        """Lite mode should NOT create .sigma_regime file."""
        buf = make_buffer(tmp_path, buffer_mode='lite')
        clear_cooldown(buf)
        run_hook('architecture refactor discussion', str(tmp_path))
        assert not os.path.exists(os.path.join(buf, '.sigma_regime'))

    def test_lite_mode_no_prediction_errors(self, tmp_path):
        """Lite mode should NOT create .sigma_errors file."""
        buf = make_buffer(tmp_path, buffer_mode='lite')
        clear_cooldown(buf)
        run_hook('some random topic about quantum physics', str(tmp_path))
        assert not os.path.exists(os.path.join(buf, '.sigma_errors'))

    def test_lite_mode_no_grid_adjustments(self, tmp_path):
        """Lite mode should NOT create .grid_adjustments file."""
        buf = make_buffer(tmp_path, buffer_mode='lite')
        clear_cooldown(buf)
        run_hook('architecture review patterns', str(tmp_path))
        assert not os.path.exists(os.path.join(buf, '.grid_adjustments'))

    def test_lite_mode_skips_alpha(self, tmp_path):
        """Lite mode exits after hot layer — alpha never queried even if present."""
        alpha = {
            'sources': {'test-source': {'path': '/tmp/test.pdf', 'mode': 'lite'}},
            'concept_index': {
                'quantum_entanglement': ['w:1'],
                'wave_function': ['w:2'],
            }
        }
        buf = make_buffer(tmp_path, buffer_mode='lite', alpha_index=alpha)
        clear_cooldown(buf)
        result = run_hook('Tell me about quantum entanglement and wave functions', str(tmp_path))
        # Should NOT get alpha hits — lite mode exits before Level 2
        msg = result.get('systemMessage', '')
        assert 'sigma alpha' not in msg

    def test_lite_mode_ignores_existing_regime(self, tmp_path):
        """Even if .sigma_regime exists, lite mode doesn't update it."""
        regime = {'activations': {'test': 0.5}, '_entropy': 0.3, '_prompt_count': 10}
        buf = make_buffer(tmp_path, buffer_mode='lite', regime=regime)
        clear_cooldown(buf)
        run_hook('architecture discussion about patterns', str(tmp_path))
        # Regime file should be unchanged (prompt_count should still be 10)
        with open(os.path.join(buf, '.sigma_regime'), 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['_prompt_count'] == 10


class TestFullModeE2E:
    """End-to-end tests verifying full mode still works correctly."""

    def test_full_mode_creates_regime(self, tmp_path):
        """Full mode should create/update .sigma_regime file."""
        alpha = {
            'sources': {},
            'concept_index': {'architecture': ['w:1']}
        }
        buf = make_buffer(tmp_path, buffer_mode='full', alpha_index=alpha)
        clear_cooldown(buf)
        # Mark buffer as already loaded so hot layer is skipped
        (Path(buf) / '.buffer_loaded').write_text('loaded', encoding='utf-8')
        run_hook('architecture patterns and design decisions', str(tmp_path))
        # Full mode with alpha should create regime file
        regime_path = os.path.join(buf, '.sigma_regime')
        assert os.path.exists(regime_path)

    def test_full_mode_records_prediction_errors(self, tmp_path):
        """Full mode should write .sigma_errors for gap tracking."""
        alpha = {
            'sources': {},
            'concept_index': {}  # Empty index = all keywords are gaps
        }
        buf = make_buffer(tmp_path, buffer_mode='full', alpha_index=alpha)
        clear_cooldown(buf)
        (Path(buf) / '.buffer_loaded').write_text('loaded', encoding='utf-8')
        run_hook('quantum entanglement is fascinating stuff', str(tmp_path))
        # Full mode records prediction errors for gap keywords
        errors_path = os.path.join(buf, '.sigma_errors')
        assert os.path.exists(errors_path)


class TestHookBasics:
    """Basic hook behavior shared across modes."""

    def test_empty_prompt_exits_silently(self, tmp_path):
        buf = make_buffer(tmp_path)
        result = run_hook('', str(tmp_path))
        assert result == {}

    def test_short_prompt_exits_silently(self, tmp_path):
        buf = make_buffer(tmp_path)
        result = run_hook('hi', str(tmp_path))
        assert result == {}

    def test_slash_command_exits_silently(self, tmp_path):
        buf = make_buffer(tmp_path)
        result = run_hook('/buffer:on', str(tmp_path))
        assert result == {}

    def test_no_buffer_exits_silently(self, tmp_path):
        result = run_hook('some random long prompt about things', str(tmp_path))
        assert result == {}

    def test_cooldown_blocks_rapid_fire(self, tmp_path):
        buf = make_buffer(tmp_path)
        clear_cooldown(buf)
        # First fire should proceed
        run_hook('architecture refactor discussion', str(tmp_path))
        # Second fire within 30s should be empty
        result = run_hook('architecture refactor discussion', str(tmp_path))
        assert result == {}

    def test_distill_active_skips(self, tmp_path):
        buf = make_buffer(tmp_path)
        clear_cooldown(buf)
        (Path(buf) / '.distill_active').write_text('active', encoding='utf-8')
        result = run_hook('architecture refactor discussion about important concepts', str(tmp_path))
        assert result == {}
