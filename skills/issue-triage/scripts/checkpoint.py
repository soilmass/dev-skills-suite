#!/usr/bin/env python3
"""Write and read the two-phase checkpoint record for a multi-step
Command Skill (SDS-S-053, SDS-S-055, SDS-S-101).

Usage:
    checkpoint.py <skill> <key> --step <name> --status pending
        [--pre-state-file <json>] [--compensating-action "<text>"]
        [--state-dir <dir>]
    checkpoint.py <skill> <key> --step <name> --status completed
        [--post-state-file <json>] [--state-dir <dir>]
    checkpoint.py <skill> <key> --show [--state-dir <dir>]

The record lives at <state-dir>/<skill>/<key>.json (SDS-S-100).
<state-dir> defaults to <family-root>/.skills-state, where the family
root is the nearest ancestor of the working directory containing a
kit/ directory; pass --state-dir explicitly when running outside a
family checkout (evals do, pointing at a gitignored scratch dir).

Record shape:
    {"skill", "key", "steps": [
        {"step", "status": "pending"|"completed", "startedAt",
         "completedAt"?, "preState", "compensatingAction", "postState"?}
    ]}

`--status pending` appends a new step record BEFORE the mutating call
it protects. `--status completed` updates the matching pending step
immediately after the call succeeds. A resumed invocation reads the
file with --show: a `pending` step is possibly-applied and must be
check-before-act'ed; a `completed` step is skipped (SDS-C-046).

This script is local-write only (Effect Ladder rung 4): it never
performs the mutation it records — the mutating command is issued by
the model as a direct, unwrapped tool call after Confirm (SDS-S-051).

Prints the record path on the first line and the full record JSON
after it. Exit 1 with "ERROR: ..." on stderr for a missing family
root without --state-dir, an unreadable/unparseable existing record,
an unreadable state file argument, or completing a step that has no
pending record.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_family_root(start):
    for candidate in [start, *start.parents]:
        if (candidate / "kit").is_dir():
            return candidate
    return None


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json_file(path, what):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not read {what} file {path}: {e}")


def read_record(path, skill, key):
    if not path.exists():
        return {"skill": skill, "key": key, "steps": []}
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: existing checkpoint {path} is unreadable: {e}")
    if record.get("skill") != skill or record.get("key") != key:
        sys.exit(f"ERROR: checkpoint {path} belongs to {record.get('skill')}/{record.get('key')}, not {skill}/{key}")
    return record


def take(args, flag, required_value=True):
    if flag not in args:
        return None
    i = args.index(flag)
    if required_value:
        if i + 1 >= len(args):
            sys.exit(f"ERROR: {flag} requires a value")
        value = args[i + 1]
        del args[i:i + 2]
        return value
    del args[i]
    return True


def main():
    args = sys.argv[1:]
    state_dir = take(args, "--state-dir")
    step = take(args, "--step")
    status = take(args, "--status")
    pre_state_file = take(args, "--pre-state-file")
    post_state_file = take(args, "--post-state-file")
    compensating = take(args, "--compensating-action")
    show = take(args, "--show", required_value=False)
    if len(args) != 2:
        sys.exit("ERROR: usage: checkpoint.py <skill> <key> (--step <name> --status pending|completed | --show) [--state-dir <dir>]")
    skill, key = args

    if state_dir is None:
        root = find_family_root(Path.cwd().resolve())
        if root is None:
            sys.exit("ERROR: no family root (a directory containing kit/) above the working directory; pass --state-dir")
        state_dir = root / ".skills-state"
    path = Path(state_dir) / skill / f"{key}.json"
    record = read_record(path, skill, key)

    if show:
        print(path)
        print(json.dumps(record, indent=2))
        return

    if not step or status not in ("pending", "completed"):
        sys.exit("ERROR: --step <name> and --status pending|completed are required unless --show is given")

    if status == "pending":
        entry = {
            "step": step,
            "status": "pending",
            "startedAt": now(),
            "preState": load_json_file(pre_state_file, "pre-state") if pre_state_file else {},
            "compensatingAction": compensating or "none — this step must be last",
        }
        record["steps"].append(entry)
    else:
        pending = [s for s in record["steps"] if s["step"] == step and s["status"] == "pending"]
        if not pending:
            sys.exit(f"ERROR: no pending record for step {step!r} in {path}; write --status pending before the mutating call")
        entry = pending[-1]
        entry["status"] = "completed"
        entry["completedAt"] = now()
        entry["postState"] = load_json_file(post_state_file, "post-state") if post_state_file else {}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    print(path)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
