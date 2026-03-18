#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""buffer_football.py — football lifecycle for buffer:throw / buffer:catch"""

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load buffer_utils via importlib (same pattern as compact_hook.py)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'buffer_utils', os.path.join(_script_dir, 'buffer_utils.py'))
_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils)
find_buffer_dir = _utils.find_buffer_dir

# Load safe_io via importlib (same pattern)
try:
    _sio_spec = importlib.util.spec_from_file_location(
        'safe_io', os.path.join(_script_dir, 'safe_io.py'))
    _sio = importlib.util.module_from_spec(_sio_spec)
    _sio_spec.loader.exec_module(_sio)
    atomic_write_json = _sio.atomic_write_json
    check_schema_version = _sio.check_schema_version
    SchemaVersionError = _sio.SchemaVersionError
except Exception:
    # Fallback: if safe_io is unavailable, define stubs so the script doesn't break
    def atomic_write_json(path, data, indent=2):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
    def check_schema_version(data, max_supported, path='<unknown>'):
        return data.get('schema_version', 1) if isinstance(data, dict) else 1
    class SchemaVersionError(ValueError):
        pass

SCHEMA_PATH = Path(_script_dir).parent.parent / "schemas" / "football.schema.json"


def _resolve_buffer(cwd):
    bd = find_buffer_dir(Path(cwd) if cwd else Path.cwd())
    if bd is None:
        print(json.dumps({"error": "buffer directory not found"}))
        sys.exit(1)
    return Path(bd)

def _football(bd): return Path(bd) / "football.json"
def _micro(bd):    return Path(bd) / "football-micro.json"
def _hot(bd):      return Path(bd) / "handoff.json"


def cmd_status(args):
    bd = _resolve_buffer(args.cwd)
    has_trunk = _hot(bd).exists()
    has_micro = _micro(bd).exists()
    if has_trunk and has_micro:
        session_type = "ambiguous"
        print("WARNING: both handoff.json and football-micro.json found", file=sys.stderr)
    elif has_trunk:
        session_type = "planner"
    elif has_micro:
        session_type = "worker"
    else:
        session_type = "unknown"
    fp = _football(bd)
    football_state = throw_type = None
    stale = False
    if fp.exists():
        try:
            with open(fp, encoding='utf-8-sig') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
        # V2: schema version check
        try:
            check_schema_version(data, max_supported=1, path=str(fp))
        except SchemaVersionError as e:
            print(f"warning: {e}", file=sys.stderr)
        # H3: empty dict is corrupt, not normal
        if data == {}:
            print("warning: football.json is empty — treating as corrupt", file=sys.stderr)
            football_state = "corrupt"
        else:
            football_state = data.get("state")
        throw_type = data.get("throw_type")
        if football_state == "caught":
            thrown_at = data.get("thrown_at", "")
            try:
                age = (datetime.now() - datetime.strptime(thrown_at, "%Y-%m-%d")).days
                stale = age >= 3
            except ValueError:
                pass
    result = {"session_type": session_type, "football_state": football_state,
              "throw_type": throw_type, "buffer_dir": str(bd)}
    if stale:
        result["stale"] = True
    print(json.dumps(result))


def cmd_validate(args):
    fp = Path(args.football)
    if not fp.exists():
        print(json.dumps({"valid": False, "error": f"not found: {fp}"}))
        sys.exit(1)
    import jsonschema
    try:
        with open(fp, encoding='utf-8-sig') as f:
            data = json.load(f)
        with open(SCHEMA_PATH, encoding='utf-8-sig') as f:
            schema = json.load(f)
        jsonschema.validate(data, schema)
        print(json.dumps({"valid": True}))
    except jsonschema.ValidationError as e:
        print(json.dumps({"valid": False, "error": e.message}))
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"valid": False, "error": f"JSON error: {e}"}))
        sys.exit(1)


def _slug(description):
    words = description.strip().split()[:5]
    return "-".join(re.sub(r"[^\w]", "", w).lower() for w in words if w) or "football"


def cmd_archive(args):
    fp = Path(args.football)
    if not fp.exists():
        print(json.dumps({"error": f"not found: {fp}"}))
        sys.exit(1)
    try:
        with open(fp, encoding='utf-8-sig') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(json.dumps({"error": f"corrupt football file: {fp}"}))
        sys.exit(1)
    data["state"] = "absorbed"
    desc = data.get("planner_payload", {}).get("thread", {}).get("description", "football")
    date = data.get("thrown_at", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    archive_dir = fp.parent / "footballs"
    archive_dir.mkdir(exist_ok=True)
    dest = archive_dir / f"{date}-{_slug(desc)}.json"
    atomic_write_json(str(dest), data)
    fp.unlink()
    print(json.dumps({"archived_to": str(dest)}))


def _pack_planner(args, bd, fp, throw_count, today):
    existing = {}
    if fp.exists():
        try:
            with open(fp, encoding='utf-8-sig') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}
    thread = json.loads(args.thread) if args.thread else {}
    payload = {"thread": thread}
    if args.type == "heavy":
        context = {"relevant_decisions": [], "alpha_refs": [], "orientation_fragment": "", "dialogue_style": None}
        hot = _hot(bd)
        if hot.exists():
            try:
                with open(hot, encoding='utf-8-sig') as f:
                    trunk = json.load(f)
            except (json.JSONDecodeError, OSError):
                trunk = {}
            # H4: warn if handoff.json is empty/hollow
            if trunk == {} or "orientation" not in trunk:
                print("warning: handoff.json is empty/hollow — planner context will be blank", file=sys.stderr)
            o = trunk.get("orientation", {})
            frags = [o.get("core_insight", ""), o.get("practical_warning", "")]
            context["orientation_fragment"] = " ".join(f for f in frags if f)
            context["dialogue_style"] = trunk.get("instance_notes", {}).get("dialogue_style", None)
            context["relevant_decisions"] = trunk.get("recent_decisions", [])[:3]
        context["alpha_refs"] = json.loads(args.alpha_refs) if args.alpha_refs else []
        payload["context"] = context
    data = {**existing,
            "schema_version": 1, "mode": "football", "state": "in_flight",
            "throw_type": args.type, "thrown_by": "planner",
            "throw_count": throw_count, "thrown_at": today,
            "planner_payload": payload,
            "worker_output": existing.get("worker_output", {})}
    atomic_write_json(str(fp), data)
    print(json.dumps({"packed": True, "throw_count": throw_count}))


def _pack_worker(args, bd, fp, throw_count, today):
    micro = {}
    micro_path = _micro(bd)
    if micro_path.exists():
        try:
            with open(micro_path, encoding='utf-8-sig') as f:
                micro = json.load(f)
        except (json.JSONDecodeError, OSError):
            micro = {}
    # H5: warn if football-micro.json is empty
    if micro == {}:
        print("warning: football-micro.json is empty — worker output may be incomplete", file=sys.stderr)
    existing = {}
    if fp.exists():
        try:
            with open(fp, encoding='utf-8-sig') as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}
    if args.type == "heavy":
        worker_output = {
            "completed": micro.get("completed_tasks", []),
            "changes_made": micro.get("decisions_made", []),
            "surprised_by": [],
            "next_action": micro.get("active_task", ""),
            "flagged_for_trunk": micro.get("flagged_for_trunk", []),
        }
    else:
        worker_output = {
            "completed": json.loads(args.completed) if args.completed else [],
            "changes_made": json.loads(args.changes) if args.changes else [],
            "surprised_by": [],
            "next_action": args.next_action or "",
            "flagged_for_trunk": micro.get("flagged_for_trunk", []),
        }
    existing.update({"throw_count": throw_count, "thrown_by": "worker",
                     "throw_type": args.type, "thrown_at": today,
                     "state": "returned", "worker_output": worker_output})
    atomic_write_json(str(fp), existing)
    print(json.dumps({"packed": True, "throw_count": throw_count}))


def cmd_unpack(args):
    fp = Path(args.football)
    if not fp.exists():
        print(json.dumps({"error": f"not found: {fp}"}))
        sys.exit(1)
    try:
        with open(fp, encoding='utf-8-sig') as f:
            data = json.load(f)
        # V2: schema version check
        try:
            check_schema_version(data, max_supported=1, path=str(fp))
        except SchemaVersionError as e:
            print(f"warning: {e}", file=sys.stderr)
        print(json.dumps(data, indent=2))
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"corrupt football file: {e}"}))
        sys.exit(1)


def cmd_flag(args):
    bd = _resolve_buffer(args.cwd)
    micro_path = _micro(bd)
    micro = {}
    if micro_path.exists():
        try:
            with open(micro_path, encoding='utf-8-sig') as f:
                micro = json.load(f)
        except (json.JSONDecodeError, OSError):
            micro = {}
    micro.setdefault("flagged_for_trunk", []).append({
        "type": args.type_flag,
        "content": json.loads(args.content),
        "rationale": args.rationale,
    })
    atomic_write_json(str(micro_path), micro)
    print(json.dumps({"flagged": True, "total_flags": len(micro["flagged_for_trunk"])}))


def cmd_pack(args):
    bd = _resolve_buffer(args.cwd)
    fp = _football(bd)
    existing_count = 0
    if fp.exists():
        try:
            with open(fp, encoding='utf-8-sig') as f:
                existing_count = json.load(f).get("throw_count", 0)
        except (json.JSONDecodeError, OSError):
            # M3: warn on corruption instead of silent reset
            print("warning: football.json corrupt — throw_count reset to 0", file=sys.stderr)
            existing_count = 0
    throw_count = existing_count + 1
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.side == "planner":
        _pack_planner(args, bd, fp, throw_count, today)
    else:
        _pack_worker(args, bd, fp, throw_count, today)


def main():
    parser = argparse.ArgumentParser(description="buffer:football lifecycle")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status");   p.add_argument("--cwd"); p.set_defaults(func=cmd_status)
    p = sub.add_parser("validate"); p.add_argument("--football", required=True); p.set_defaults(func=cmd_validate)
    p = sub.add_parser("archive");  p.add_argument("--football", required=True); p.set_defaults(func=cmd_archive)

    p = sub.add_parser("pack")
    p.add_argument("--side", choices=["planner", "worker"], required=True)
    p.add_argument("--type", choices=["heavy", "lite"], required=True)
    p.add_argument("--cwd"); p.add_argument("--thread"); p.add_argument("--alpha-refs", dest="alpha_refs")
    p.add_argument("--completed"); p.add_argument("--changes"); p.add_argument("--next-action", dest="next_action")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("unpack"); p.add_argument("--football", required=True); p.set_defaults(func=cmd_unpack)
    p = sub.add_parser("flag")
    p.add_argument("--type", dest="type_flag",
                   choices=["alpha_entry", "forward_note", "decision", "open_thread"], required=True)
    p.add_argument("--content", required=True); p.add_argument("--rationale", required=True)
    p.add_argument("--cwd"); p.set_defaults(func=cmd_flag)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
