"""Tests for first_run_gate.py PreToolUse hook."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE_SCRIPT = Path(__file__).parent.parent / 'distill' / 'scripts' / 'first_run_gate.py'
PYTHON = sys.executable


def run_gate(skill: str, cwd: str = '') -> dict:
    """Run the gate script with simulated hook input, return parsed output."""
    stdin_data = json.dumps({
        'hook_event_name': 'PreToolUse',
        'tool_name': 'Skill',
        'tool_params': {'skill': skill},
        'cwd': cwd,
    })
    result = subprocess.run(
        [PYTHON, str(GATE_SCRIPT)],
        input=stdin_data, capture_output=True, text=True, timeout=10,
    )
    return json.loads(result.stdout.strip()) if result.stdout.strip() else {}


def test_allows_non_distill_skill():
    """Non-distill skills pass through unconditionally."""
    assert run_gate('buffer:on') == {}
    assert run_gate('commit') == {}


def test_allows_differentiate():
    """distill:differentiate always passes — it's the setup command."""
    assert run_gate('distill:differentiate') == {}
    assert run_gate('differentiate') == {}


def test_blocks_without_project_skill(tmp_path):
    """Distill skills blocked when no project SKILL.md exists."""
    # Create a .git dir so the gate finds a project root
    (tmp_path / '.git').mkdir()
    result = run_gate('distill:analyze', cwd=str(tmp_path))
    assert result.get('decision') == 'block'
    assert 'differentiate' in result.get('reason', '')


def test_allows_with_project_skill(tmp_path):
    """Distill skills pass when project SKILL.md exists."""
    (tmp_path / '.git').mkdir()
    skill_dir = tmp_path / '.claude' / 'skills' / 'distill'
    skill_dir.mkdir(parents=True)
    (skill_dir / 'SKILL.md').write_text('# test', encoding='utf-8')
    result = run_gate('distill:analyze', cwd=str(tmp_path))
    assert result == {}


def test_allows_with_config_yaml(tmp_path):
    """Distill skills pass when distill.config.yaml exists (lite mode marker)."""
    (tmp_path / '.git').mkdir()
    claude_dir = tmp_path / '.claude'
    claude_dir.mkdir()
    (claude_dir / 'distill.config.yaml').write_text('mode: lite', encoding='utf-8')
    result = run_gate('distill:extract', cwd=str(tmp_path))
    assert result == {}


def test_blocks_all_distill_variants(tmp_path):
    """All distill sub-skills are gated."""
    (tmp_path / '.git').mkdir()
    for skill in ['distill:analyze', 'distill:extract', 'distill:integrate', 'distill:distill', 'distill']:
        result = run_gate(skill, cwd=str(tmp_path))
        assert result.get('decision') == 'block', f'{skill} should be blocked'


def test_blocks_from_subdirectory(tmp_path):
    """Gate finds project root from a subdirectory."""
    (tmp_path / '.git').mkdir()
    subdir = tmp_path / 'src' / 'deep'
    subdir.mkdir(parents=True)
    result = run_gate('distill:analyze', cwd=str(subdir))
    assert result.get('decision') == 'block'


def test_allows_from_subdirectory_with_skill(tmp_path):
    """Gate finds project root and SKILL.md from a subdirectory."""
    (tmp_path / '.git').mkdir()
    skill_dir = tmp_path / '.claude' / 'skills' / 'distill'
    skill_dir.mkdir(parents=True)
    (skill_dir / 'SKILL.md').write_text('# test', encoding='utf-8')
    subdir = tmp_path / 'src' / 'deep'
    subdir.mkdir(parents=True)
    result = run_gate('distill:analyze', cwd=str(subdir))
    assert result == {}


def test_finds_root_via_claude_dir_no_git(tmp_path):
    """Project root discovered via .claude/ when no .git/ exists."""
    claude_dir = tmp_path / '.claude'
    claude_dir.mkdir()
    result = run_gate('distill:analyze', cwd=str(tmp_path))
    assert result.get('decision') == 'block'


def test_allows_via_claude_dir_with_config(tmp_path):
    """Config marker found via .claude/-only root (no .git)."""
    claude_dir = tmp_path / '.claude'
    claude_dir.mkdir()
    (claude_dir / 'distill.config.yaml').write_text('mode: lite', encoding='utf-8')
    result = run_gate('distill:analyze', cwd=str(tmp_path))
    assert result == {}


def test_fails_open_on_bad_json():
    """Malformed stdin should allow (fail open)."""
    result = subprocess.run(
        [PYTHON, str(GATE_SCRIPT)],
        input='not json at all', capture_output=True, text=True, timeout=10,
    )
    output = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
    assert output == {}


def test_fails_open_on_empty_stdin():
    """Empty stdin should allow (fail open)."""
    result = subprocess.run(
        [PYTHON, str(GATE_SCRIPT)],
        input='', capture_output=True, text=True, timeout=10,
    )
    output = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
    assert output == {}


def test_allows_non_skill_tool():
    """Non-Skill tool names pass through."""
    stdin_data = json.dumps({
        'hook_event_name': 'PreToolUse',
        'tool_name': 'Bash',
        'tool_params': {'command': 'echo hello'},
        'cwd': '',
    })
    result = subprocess.run(
        [PYTHON, str(GATE_SCRIPT)],
        input=stdin_data, capture_output=True, text=True, timeout=10,
    )
    output = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
    assert output == {}
