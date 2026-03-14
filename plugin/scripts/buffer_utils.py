#!/usr/bin/env python3
"""
Session Buffer — Shared Discovery Utilities

Provides buffer directory discovery for hook scripts (sigma_hook, compact_hook).
Registry-primary lookup with git-guarded walk-up fallback.

Import via importlib (see sigma_hook.py for pattern):
    spec = importlib.util.spec_from_file_location(
        'buffer_utils', os.path.join(script_dir, 'buffer_utils.py'))
    utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(utils)
"""

import os
import json


REGISTRY_PATH = os.path.join(os.path.expanduser('~'), '.claude', 'buffer', 'projects.json')


def is_git_repo(path):
    """Check if path is a git repo root (has .git/ directory)."""
    try:
        return os.path.isdir(os.path.join(path, '.git'))
    except (TypeError, OSError):
        return False


def match_cwd_to_project(cwd, repo_root):
    """Check if cwd is inside (or equal to) repo_root.

    Uses os.path.normcase for Windows case-insensitivity.
    Trailing separator guard prevents /proj matching /project-2.
    """
    norm_cwd = os.path.normcase(os.path.abspath(cwd))
    norm_root = os.path.normcase(os.path.abspath(repo_root))
    if norm_cwd == norm_root:
        return True
    return norm_cwd.startswith(norm_root + os.sep)
