# plugin/scripts/telemetry.py
"""
Session Buffer — Telemetry Utility

Append-only event logging to .claude/buffer/telemetry.jsonl.
Imported by sigma_hook and compact_hook via importlib pattern.
Also provides a session-end CLI subcommand for /buffer:off.

Design principle: fail-silent. Telemetry must never break a hook.
"""

import json
import os
import sys
from datetime import datetime, timezone


def tier_from_percentage(used_pct):
    """Return headroom tier name from context usage percentage.

    Thresholds use >= boundaries:
      >= 93 → 'critical'
      >= 85 → 'warn'
      >= 70 → 'watch'
      < 70  → None
    """
    if used_pct >= 93:
        return 'critical'
    if used_pct >= 85:
        return 'warn'
    if used_pct >= 70:
        return 'watch'
    return None


def cache_ratio(cache_read, cache_creation, input_tokens):
    """Compute cache read ratio.

    Returns cache_read / (cache_read + cache_creation + input_tokens).
    Returns 0.0 if denominator is zero (avoids ZeroDivisionError).
    """
    total = cache_read + cache_creation + input_tokens
    if total == 0:
        return 0.0
    return cache_read / total


def emit(buffer_dir, event_dict):
    """Append a timestamped event to telemetry.jsonl.

    Auto-adds 'ts' field with ISO 8601 UTC timestamp.
    Creates file if it doesn't exist.
    Fail-silent: logs to stderr on error, never raises.
    """
    try:
        entry = dict(event_dict)
        entry['ts'] = datetime.now(timezone.utc).isoformat()
        telemetry_path = os.path.join(buffer_dir, 'telemetry.jsonl')
        with open(telemetry_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"telemetry: emit failed: {e}", file=sys.stderr)


def cmd_session_end(buffer_dir):
    """Compute and emit session-end summary from today's telemetry.

    Scans telemetry.jsonl for today's entries, computes:
      - compactions: count of 'compact' events today
      - warnings_emitted: count of 'headroom_warning' events today
      - peak_context_pct: max context_pct across today's events
      - off_count: from .session_active

    Called by /buffer:off Step 13.
    """
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    telemetry_path = os.path.join(buffer_dir, 'telemetry.jsonl')

    compactions = 0
    warnings = 0
    peak_pct = 0

    try:
        with open(telemetry_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get('ts', '')
                if not ts.startswith(today):
                    continue
                event = entry.get('event', '')
                if event == 'compact':
                    compactions += 1
                elif event == 'headroom_warning':
                    warnings += 1
                pct = entry.get('context_pct', 0)
                if isinstance(pct, (int, float)) and pct > peak_pct:
                    peak_pct = pct
    except FileNotFoundError:
        pass  # No telemetry yet — still emit session_end with zeros
    except Exception as e:
        print(f"telemetry: session-end scan failed: {e}", file=sys.stderr)

    # Read off_count from .session_active
    off_count = 0
    session_active_path = os.path.join(buffer_dir, '.session_active')
    try:
        with open(session_active_path, 'r', encoding='utf-8') as f:
            sa = json.load(f)
            off_count = int(sa.get('off_count', 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
        pass

    emit(buffer_dir, {
        'event': 'session_end',
        'compactions': compactions,
        'off_count': off_count,
        'warnings_emitted': warnings,
        'peak_context_pct': peak_pct,
    })


if __name__ == '__main__':
    # CLI interface for /buffer:off
    if len(sys.argv) >= 2 and sys.argv[1] == 'session-end':
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('command')
        parser.add_argument('--buffer-dir', required=True)
        args = parser.parse_args()
        cmd_session_end(args.buffer_dir)
    else:
        print("Usage: telemetry.py session-end --buffer-dir <path>",
              file=sys.stderr)
        sys.exit(1)
