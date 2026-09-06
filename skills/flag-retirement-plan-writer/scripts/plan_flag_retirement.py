#!/usr/bin/env python3
"""Turn a feature-flag finding-list into a plan-doc for retiring dead flags
(kit/shapes/plan-doc.schema.json).

Usage:
    plan_flag_retirement.py <finding-list.json> --as-of ISO
        [--older-than-days N]

Effect Ladder rung 1 (SDS-S-060): the finding-list is read; nothing is
run and nothing is written. The input is `feature-flag-inventory`'s
finding-list (kit/shapes/finding-list.schema.json): each result's
`properties` carries `flag`, and (for the two stale rules) `ageDays`
and `checks`; `runs[*].tool.properties.flags` carries the full
inventory — one record per flag with `files`, `enabled`, `rollout`,
`ageDays`, `owner`, `checks`, `configured` — used here to find the
files a flag touches and its age even where a result's own properties
omit it.

Only three ruleIds produce a retirement step:

    flag/fully-rolled-out   enabled at 100% and still checked -> the
                            enabled branch survives; the check and the
                            disabled branch are removed
    flag/permanently-off    disabled and still checked -> the disabled
                            branch survives; the check and the enabled
                            branch are removed
    flag/unreferenced       configured but checked nowhere -> nothing
                            to remove from code, only the definition

`flag/unowned` and `flag/unregistered` are ownership and registration
findings, not retirement candidates — a flag nobody owns or nobody
configured is not thereby dead code — and produce no step.

`--as-of` (REQUIRED, SDS-S-064) is recorded in the plan's goal so the
count of retired flags is reproducible; it is not used to recompute
age (the inventory's `ageDays` is already relative to the audit's own
`--as-of`). `--older-than-days` (default 0) drops a candidate flag
whose inventory `ageDays` is below it — a flag reported stale by a run
with a shorter `--stale-days` window than the caller wants to act on
yet.

The plan has three phases, in order:

    remove dead branches       one step per fully-rolled-out or
                                permanently-off flag; riskIfFails low;
                                rollback "git revert <commit>"
    delete flag definitions    one step per retired flag, including
                                unreferenced ones; riskIfFails medium;
                                rollback re-adds the definition from
                                the reverted commit
    clean the flag provider/config
                                one step naming every retired flag,
                                last because the code and the
                                definitions must be gone first;
                                riskIfFails low; rollback "git revert
                                <commit>"

Nothing to retire yields a plan-doc with one phase ("nothing to do")
and one step whose rollback says none is needed and whose
checkpointAfter is false (SDS-C-033).

Prints one plan-doc. Exit 1 with "ERROR: ..." on stderr for input that
is not JSON, not an object with a non-empty `runs` array, or whose
results lack `ruleId` (findings-invalid), or for a missing or
unparseable `--as-of` or a non-integer `--older-than-days`
(as-of-invalid).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RETIREMENT_RULES = {"flag/fully-rolled-out", "flag/permanently-off", "flag/unreferenced"}
NO_STEP_RULES = {"flag/unowned", "flag/unregistered"}


def parse_ts(value, what):
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        sys.exit(f"ERROR: {what} {value!r} is not an ISO-8601 timestamp (as-of-invalid)")
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def load_findings(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"ERROR: could not read {path} (findings-invalid): {e}")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {path} is not JSON (findings-invalid): {e}")
    if not isinstance(doc, dict) or not isinstance(doc.get("runs"), list) or not doc["runs"]:
        sys.exit(f"ERROR: {path} is not a finding-list: no non-empty runs array (findings-invalid)")
    results, inventory = [], {}
    for run in doc["runs"]:
        if not isinstance(run, dict) or not isinstance(run.get("results"), list):
            sys.exit(f"ERROR: {path} is not a finding-list: a run lacks a results array (findings-invalid)")
        for r in run["results"]:
            if not isinstance(r, dict) or "ruleId" not in r:
                sys.exit(f"ERROR: {path} is not a finding-list: a result lacks ruleId (findings-invalid)")
            results.append(r)
        flags = (((run.get("tool") or {}).get("properties") or {}).get("flags")) or []
        for rec in flags:
            if isinstance(rec, dict) and rec.get("flag"):
                inventory[rec["flag"]] = rec
    return results, inventory


def branch_step(rule, flag, files):
    where = ", ".join(files) if files else "its call sites"
    if rule == "flag/fully-rolled-out":
        desc = (f"Remove the dead branch for {flag}: in {where}, keep the enabled branch "
                f"(the flag is fully rolled out) and delete the disabled branch and the check")
    else:
        desc = (f"Remove the dead branch for {flag}: in {where}, keep the disabled branch "
                f"(the flag has been permanently off) and delete the enabled branch and the check")
    return {"description": desc, "riskIfFails": "low", "rollback": "git revert <commit>", "checkpointAfter": True}


def definition_step(flag):
    return {
        "description": f"Delete the definition of {flag} from the flag configuration and its provider",
        "riskIfFails": "medium",
        "rollback": "re-add the definition from the reverted commit",
        "checkpointAfter": True,
    }


def cleanup_step(flags):
    return {
        "description": f"Clean the flag provider and configuration of the retired flags: {', '.join(flags)}",
        "riskIfFails": "low",
        "rollback": "git revert <commit>",
        "checkpointAfter": True,
    }


def main():
    args = sys.argv[1:]
    opts = {"--as-of": None, "--older-than-days": "0"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: plan_flag_retirement.py <finding-list.json> --as-of ISO [--older-than-days N]")
    if not opts["--as-of"]:
        sys.exit("ERROR: --as-of is required so the retirement count is reproducible (as-of-invalid)")
    as_of = parse_ts(opts["--as-of"], "--as-of")
    try:
        older_than_days = int(opts["--older-than-days"])
    except ValueError:
        sys.exit("ERROR: --older-than-days must be an integer (as-of-invalid)")

    results, inventory = load_findings(args[0])

    branch_flags, retired_flags, seen = [], [], set()
    for r in results:
        rule = r.get("ruleId")
        if rule in NO_STEP_RULES or rule not in RETIREMENT_RULES:
            continue
        props = r.get("properties") or {}
        flag = props.get("flag")
        if not flag or flag in seen:
            continue
        rec = inventory.get(flag, {})
        age = rec.get("ageDays", props.get("ageDays"))
        if age is not None and age < older_than_days:
            continue
        seen.add(flag)
        files = rec.get("files") or []
        retired_flags.append(flag)
        if rule in ("flag/fully-rolled-out", "flag/permanently-off"):
            branch_flags.append((rule, flag, files))

    if not retired_flags:
        phases = [{
            "name": "nothing to do",
            "steps": [{
                "description": "No flag in this finding-list qualifies for retirement as of "
                                f"{as_of.isoformat()}",
                "riskIfFails": "low",
                "rollback": "none needed — no step was taken",
                "checkpointAfter": False,
            }],
        }]
    else:
        phases = [
            {"name": "remove dead branches", "steps": [branch_step(rule, flag, files) for rule, flag, files in branch_flags]},
            {"name": "delete flag definitions", "steps": [definition_step(flag) for flag in retired_flags]},
            {"name": "clean the flag provider/config", "steps": [cleanup_step(retired_flags)]},
        ]

    if retired_flags:
        goal = (f"Retire {len(retired_flags)} dead flag(s) ({', '.join(retired_flags)}) as of "
                f"{as_of.isoformat()}: {len(branch_flags)} dead-branch removal(s), "
                f"{len(retired_flags)} definition deletion(s), 1 provider/config cleanup")
    else:
        goal = f"Nothing to retire as of {as_of.isoformat()}: 0 dead flags found"
    print(json.dumps({"goal": goal, "phases": phases}, indent=2))


if __name__ == "__main__":
    main()
