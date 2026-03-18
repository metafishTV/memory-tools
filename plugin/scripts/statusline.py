#!/usr/bin/env python3
"""
sigma-TAP Claude Code status line script.
Reads session JSON from stdin, outputs a compact status line.

Also performs headroom tier detection (Layer 2) since the statusline
is the only script that receives context_window data from Claude Code.
Tier crossings are written to .sigma_headroom_tier for the sigma hook
to read and inject warnings on the next UserPromptSubmit.
"""

import importlib.util
import json
import os
import sys

# Load sibling modules via importlib (fail-silent — statusline must never crash)
_script_dir = os.path.dirname(os.path.abspath(__file__))

_telemetry_mod = None
try:
    _spec = importlib.util.spec_from_file_location(
        'telemetry', os.path.join(_script_dir, 'telemetry.py'))
    _telemetry_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_telemetry_mod)
except Exception:
    pass

_buffer_utils = None
try:
    _spec = importlib.util.spec_from_file_location(
        'buffer_utils', os.path.join(_script_dir, 'buffer_utils.py'))
    _buffer_utils = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_buffer_utils)
except Exception:
    pass


def read_handoff(buffer_dir):
    handoff_path = os.path.join(buffer_dir, "handoff.json")
    if not os.path.isfile(handoff_path):
        return None
    try:
        with open(handoff_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_git_branch(cwd):
    # Read git branch without subprocess: parse .git/HEAD directly.
    git_head = os.path.join(cwd, ".git", "HEAD")
    if not os.path.isfile(git_head):
        # Walk up to find repo root.
        parts = cwd.replace("\\", "/").split("/")
        for i in range(len(parts) - 1, 0, -1):
            candidate = "/".join(parts[:i]) + "/.git/HEAD"
            if os.path.isfile(candidate):
                git_head = candidate
                break
        else:
            return None
    try:
        with open(git_head, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
        # Detached HEAD — show short hash.
        return content[:7]
    except Exception:
        return None


def _detect_headroom(buffer_dir, context_window):
    """Detect tier crossings and emit telemetry. Returns (used_pct, tier)."""
    if not context_window or not _telemetry_mod:
        return None, None

    used_pct = context_window.get('used_percentage')
    if used_pct is None:
        return None, None

    try:
        used_pct = float(used_pct)
    except (ValueError, TypeError):
        return None, None

    current_tier = _telemetry_mod.tier_from_percentage(used_pct)

    # Read last emitted tier
    tier_path = os.path.join(buffer_dir, '.sigma_headroom_tier')
    last_tier = None
    try:
        with open(tier_path, 'r', encoding='utf-8') as f:
            last_tier = f.read().strip() or None
    except (FileNotFoundError, OSError):
        pass

    # On tier crossing (including dropping back to None), update file and emit
    if current_tier != last_tier:
        try:
            if current_tier is not None:
                with open(tier_path, 'w', encoding='utf-8') as f:
                    f.write(current_tier)
            else:
                # Dropped below watch — remove tier file
                try:
                    os.remove(tier_path)
                except FileNotFoundError:
                    pass
        except OSError:
            pass

        # Emit telemetry on upward crossings only (entering a tier)
        if current_tier is not None:
            cur_usage = context_window.get('current_usage') or {}
            cr = None
            cache_read = cur_usage.get('cache_read_input_tokens')
            cache_creation = cur_usage.get('cache_creation_input_tokens')
            input_tok = cur_usage.get('input_tokens')
            if cache_read is not None and cache_creation is not None and input_tok is not None:
                cr = _telemetry_mod.cache_ratio(
                    float(cache_read), float(cache_creation), float(input_tok))

            event = {
                'event': 'headroom_warning',
                'context_pct': int(used_pct),
                'tier': current_tier,
            }
            if cr is not None:
                event['cache_ratio'] = round(cr, 2)
            _telemetry_mod.emit(buffer_dir, event)

    return used_pct, current_tier


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    # Extract context_window (nested object in statusline input)
    context_window = data.get('context_window') or {}
    used_pct_raw = context_window.get('used_percentage')

    cwd = data.get("cwd") or data.get("workspace", {}).get("current_dir") or os.getcwd()
    # Normalise Windows backslashes.
    cwd = cwd.replace("\\", "/")

    # Find buffer dir — prefer registry/walk-up, fall back to cwd-relative
    buffer_dir = None
    if _buffer_utils:
        buffer_dir = _buffer_utils.find_buffer_dir(cwd)
    if not buffer_dir:
        buffer_dir = os.path.join(cwd, ".claude", "buffer").replace("\\", "/")

    handoff = read_handoff(buffer_dir)

    # Headroom detection (writes tier file + telemetry for sigma hook)
    detected_pct, detected_tier = _detect_headroom(buffer_dir, context_window)

    parts = []

    if handoff is None:
        parts.append("buf:off")
    else:
        # 1. Buffer mode (full/lite).
        buf_mode = handoff.get("buffer_mode", "?")
        parts.append(f"buf:{buf_mode}")

        # 2. Active work phase.
        active_work = handoff.get("active_work") or {}
        phase = active_work.get("current_phase")
        if phase:
            # Truncate long phase descriptions to first 20 chars.
            short = phase if len(phase) <= 20 else phase[:18] + ".."
            parts.append(f"phase:{short}")

        # 3. Open threads count.
        threads = handoff.get("open_threads") or []
        if threads:
            parts.append(f"threads:{len(threads)}")

        # 4. Last handoff date.
        meta = handoff.get("session_meta") or {}
        date = meta.get("date")
        if date:
            parts.append(f"saved:{date}")

        # 5. Distill active.
        distill_marker = os.path.join(buffer_dir, ".distill_active")
        if os.path.isfile(distill_marker):
            parts.append("distill:active")

        # 6. Compact marker (compaction just happened, not yet recovered).
        compact_marker = os.path.join(buffer_dir, ".compact_marker")
        if os.path.isfile(compact_marker):
            parts.append("compacted")

        # 7. Sigma regime.
        sigma_regime = os.path.join(buffer_dir, ".sigma_regime")
        if os.path.isfile(sigma_regime):
            parts.append("regime:on")

    # Git branch (always shown).
    branch = get_git_branch(cwd)
    if branch:
        parts.append(branch)

    # Context pressure indicator (after all other segments)
    if used_pct_raw is not None:
        try:
            pct = float(used_pct_raw)
            pct_int = int(pct)
            if pct >= 93:
                parts.append(f"ctx:{pct_int}%!!")
            elif pct >= 85:
                parts.append(f"ctx:{pct_int}%!")
            elif pct >= 70:
                parts.append(f"ctx:{pct_int}%")
        except (ValueError, TypeError):
            pass

    print(" | ".join(parts))


if __name__ == "__main__":
    main()
