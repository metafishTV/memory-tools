#!/usr/bin/env python3
"""first_run_gate.py — PreToolUse hook for Skill tool.

Blocks all distill skills (except distill:differentiate) if the project
has not been configured yet. Configuration is indicated by either:
  - <repo>/.claude/skills/distill/SKILL.md (full mode — differentiate output)
  - <repo>/.claude/distill.config.yaml (any mode — machine-readable marker)

Project root discovery: walk up from cwd looking for .git or .claude directory.

Input (stdin):  {"tool_name": "Skill", "tool_params": {"skill": "..."}, "cwd": "..."}
Output (stdout): {} to allow, {"decision": "block", "reason": "..."} to block
"""

import sys
import io
import json
import os

if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Skills that bypass the gate (differentiate IS the setup command)
ALLOWED_SKILLS = {'distill:differentiate', 'differentiate'}


def find_project_root(cwd: str) -> str | None:
    """Walk up from cwd to find project root (.git or .claude directory)."""
    current = os.path.abspath(cwd)
    while True:
        if os.path.isdir(os.path.join(current, '.git')):
            return current
        if os.path.isdir(os.path.join(current, '.claude')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def project_configured(root: str) -> bool:
    """Check if differentiate has been run (project skill or config marker exists)."""
    skill_path = os.path.join(root, '.claude', 'skills', 'distill', 'SKILL.md')
    config_path = os.path.join(root, '.claude', 'distill.config.yaml')
    return os.path.isfile(skill_path) or os.path.isfile(config_path)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print('{}')
            return
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        print('{}')
        return

    tool_name = data.get('tool_name', '')
    if tool_name != 'Skill':
        print('{}')
        return

    skill = data.get('tool_params', {}).get('skill', '')

    # Only gate distill skills
    if not skill.startswith('distill:') and skill != 'distill':
        print('{}')
        return

    # Allow differentiate through — it's the setup command
    if skill in ALLOWED_SKILLS:
        print('{}')
        return

    cwd = data.get('cwd', '')
    root = find_project_root(cwd)

    if root and project_configured(root):
        print('{}')
        return

    reason = (
        "STOP \u2014 this project has not been configured for distillation yet.\n\n"
        "Run: /distill:differentiate\n\n"
        "This one-time setup scans your project, asks a few questions, and generates "
        "a project-specific distillation skill. All other distill commands require it."
    )
    print(json.dumps({'decision': 'block', 'reason': reason}))


if __name__ == '__main__':
    main()
