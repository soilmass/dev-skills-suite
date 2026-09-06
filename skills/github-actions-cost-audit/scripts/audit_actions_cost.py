#!/usr/bin/env python3
"""Attribute GitHub Actions minutes to workflows and find the usual
waste, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    audit_actions_cost.py <repo-path> [--since ISO] [--as-of ISO] [--long-minutes N]
    audit_actions_cost.py <repo-path> --runs-json-file <path> --as-of ISO [--long-minutes N]

Requires pyyaml (the workflow files are YAML). Live mode reads
(Effect Ladder rung 3, read-only):
    gh api -X GET "repos/{owner}/{repo}/actions/runs?created=>=<since>&per_page=100" --paginate
and nothing else. `--runs-json-file` is the injectable-fixture flag
(SDS-S-065): a file in the API shape {"workflow_runs": [{id, name,
path, event, head_sha, head_branch, status, conclusion, run_attempt,
run_started_at, updated_at}]} replaces the live call. `--as-of`
injects the clock (SDS-S-064); it is REQUIRED with a fixture and
defaults to now in live mode. `--since` defaults to 30 days before
`as-of`. The workflow files under .github/workflows/ are read from the
repository for runners, triggers, and concurrency (rung 1).

Minutes are wall-clock per run (updated_at - run_started_at, rounded
up), multiplied by the runner cost of the workflow's most expensive
`runs-on` (linux 1, windows 2, macos 10, per GitHub's billing
multipliers). This approximates billed minutes — billing is per job
and includes queue-free time only, and a matrix workflow with one
macOS leg is weighted here as if every leg were macOS — and the
skill says so; the exact figure is on the billing page.

Rules emitted:

    actions-cost/top-workflow           a workflow with >= 25% of the
                                        weighted minutes -> info
    actions-cost/expensive-runner       a workflow on macos/windows
                                        runners -> warning, with the
                                        weighted minutes
    actions-cost/duplicate-trigger      a workflow that ran on both push
                                        and pull_request for the same
                                        commit -> warning
    actions-cost/no-concurrency-cancel  a workflow triggered by
                                        pull_request without
                                        `concurrency: cancel-in-progress`
                                        -> warning, with the count of
                                        superseded runs on one branch
    actions-cost/long-run               a workflow whose median run
                                        exceeds --long-minutes (default
                                        30) -> warning
    actions-cost/failed-minutes         >= 20% of minutes spent on runs
                                        that failed or were cancelled ->
                                        info
    actions-cost/reruns                 minutes spent on run attempts
                                        after the first -> info

`tool.properties` carries the window, the run count, total and
weighted minutes, and per-workflow minutes. Which waste is worth
fixing first, and whether a macOS job truly needs macOS, is the
skill's Analyze stage (SDS-S-061).

Prints one finding-list; a lean repository yields an empty `results`
array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that
is not a directory (repo-invalid), a runs file that is not the API
shape (runs-unparseable), a workflow file that is not YAML
(workflows-unparseable), a missing or malformed --as-of/--since
(as-of-invalid), or a failed live call (gh-unreachable).
"""
import json
import math
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("ERROR: pyyaml is required (pip install pyyaml)")

MULTIPLIER = [("macos", 10), ("windows", 2)]
FAILED = {"failure", "cancelled", "timed_out", "startup_failure"}


def parse_ts(s, what):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        sys.exit(f"ERROR: {what} is not an ISO-8601 timestamp (as-of-invalid): {s!r}")


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}], "properties": props}


def runner_cost(wf):
    cost = 1
    for job in (wf.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        # runs-on may be a literal, a list of labels, or a matrix
        # expression; the matrix values name the runner in the last case.
        text = json.dumps([job.get("runs-on"), job.get("strategy")]).lower()
        for name, mult in MULTIPLIER:
            if name in text:
                cost = max(cost, mult)
    return cost


def triggers(wf):
    on = wf.get("on", wf.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on}
    return set()


def cancels(wf):
    c = wf.get("concurrency")
    return isinstance(c, dict) and bool(c.get("cancel-in-progress"))


def load_workflows(root):
    out = {}
    wdir = root / ".github" / "workflows"
    for f in sorted(wdir.glob("*.y*ml")) if wdir.is_dir() else []:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            sys.exit(f"ERROR: {f.relative_to(root).as_posix()} is not valid YAML (workflows-unparseable): {e}")
        if isinstance(data, dict):
            out[f.relative_to(root).as_posix()] = data
    return out


def load_runs(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load runs file {path} (runs-unparseable): {e}")
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        sys.exit(f"ERROR: runs file {path} must be an object with a workflow_runs array (runs-unparseable)")
    return data["workflow_runs"]


def load_live(repo, since):
    q = f"repos/{{owner}}/{{repo}}/actions/runs?created=>={since.date().isoformat()}&per_page=100"
    try:
        result = subprocess.run(["gh", "api", "-X", "GET", q, "--paginate", "--jq", ".workflow_runs"], cwd=repo, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        sys.exit("ERROR: gh api actions/runs timed out after 60s (gh-unreachable)")
    if result.returncode != 0:
        sys.exit(f"ERROR: gh api actions/runs failed (gh-unreachable): {result.stderr.strip()}")
    runs = []
    for chunk in re.findall(r"\[.*?\](?=\s*\[|\s*$)", result.stdout, re.S):
        try:
            runs.extend(json.loads(chunk))
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: gh api returned unparseable JSON (runs-unparseable): {e}")
    return runs


def main():
    args = sys.argv[1:]
    opts = {"--runs-json-file": None, "--since": None, "--as-of": None, "--long-minutes": "30"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: audit_actions_cost.py <repo-path> [--runs-json-file F --as-of ISO] [--since ISO] [--long-minutes N]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    if opts["--runs-json-file"] and not opts["--as-of"]:
        sys.exit("ERROR: --as-of is required with --runs-json-file (as-of-invalid)")
    as_of = parse_ts(opts["--as-of"], "--as-of") if opts["--as-of"] else datetime.now(timezone.utc)
    since = parse_ts(opts["--since"], "--since") if opts["--since"] else as_of - timedelta(days=30)
    try:
        long_minutes = int(opts["--long-minutes"])
        assert long_minutes > 0
    except (ValueError, AssertionError):
        sys.exit(f"ERROR: --long-minutes must be a positive integer (as-of-invalid): {opts['--long-minutes']!r}")
    workflows = load_workflows(root)
    runs = load_runs(opts["--runs-json-file"]) if opts["--runs-json-file"] else load_live(root, since)

    per_wf = defaultdict(lambda: {"runs": 0, "minutes": 0, "weighted": 0, "durations": [], "failedMinutes": 0, "rerunMinutes": 0, "cost": 1})
    by_sha_event, by_branch_pr = defaultdict(set), defaultdict(set)
    total_minutes = 0
    for r in runs:
        started, ended = r.get("run_started_at"), r.get("updated_at")
        if not started or not ended:
            continue
        s, e = parse_ts(started, "run_started_at"), parse_ts(ended, "updated_at")
        if s < since or s > as_of:
            continue
        path = r.get("path") or r.get("name") or "unknown"
        wf = workflows.get(path, {})
        cost = runner_cost(wf) if wf else 1
        mins = max(1, math.ceil((e - s).total_seconds() / 60))
        p = per_wf[path]
        p["runs"] += 1
        p["minutes"] += mins
        p["weighted"] += mins * cost
        p["durations"].append(mins)
        p["cost"] = cost
        total_minutes += mins
        if r.get("conclusion") in FAILED:
            p["failedMinutes"] += mins
        if int(r.get("run_attempt") or 1) > 1:
            p["rerunMinutes"] += mins
        by_sha_event[(path, r.get("head_sha"))].add(r.get("event"))
        if r.get("event") == "pull_request":
            by_branch_pr[(path, r.get("head_branch"))].add(r.get("head_sha"))
    weighted_total = sum(p["weighted"] for p in per_wf.values())
    out = []
    for path, p in sorted(per_wf.items()):
        share = p["weighted"] / weighted_total if weighted_total else 0
        if share >= 0.25 and len(per_wf) > 1:
            out.append(finding("actions-cost/top-workflow", "info", f"{path}: {p['weighted']} weighted minute(s), {share:.0%} of the window ({p['runs']} run(s))", path, {"weightedMinutes": p["weighted"], "share": round(share, 3), "runs": p["runs"]}))
        if p["cost"] > 1:
            runner = "macos" if p["cost"] == 10 else "windows"
            out.append(finding("actions-cost/expensive-runner", "warning", f"{path} runs on {runner} ({p['cost']}x): {p['minutes']} minute(s) bill as {p['weighted']}", path, {"runner": runner, "multiplier": p["cost"], "minutes": p["minutes"], "weightedMinutes": p["weighted"]}))
        dup = [sha for (wp, sha), ev in by_sha_event.items() if wp == path and {"push", "pull_request"} <= ev]
        if dup:
            out.append(finding("actions-cost/duplicate-trigger", "warning", f"{path} ran on both push and pull_request for {len(dup)} commit(s); one trigger, or a branch filter, halves it", path, {"commits": len(dup), "examples": sorted(dup)[:3]}))
        wf = workflows.get(path)
        if wf is not None and "pull_request" in triggers(wf) and not cancels(wf):
            superseded = sum(len(shas) - 1 for (wp, _), shas in by_branch_pr.items() if wp == path and len(shas) > 1)
            if superseded:
                out.append(finding("actions-cost/no-concurrency-cancel", "warning", f"{path} runs on pull_request without concurrency cancel-in-progress; {superseded} run(s) in the window were superseded by a newer push to the same branch", path, {"supersededRuns": superseded}))
        med = statistics.median(p["durations"]) if p["durations"] else 0
        if med > long_minutes:
            out.append(finding("actions-cost/long-run", "warning", f"{path}: median run {med:g} minute(s) exceeds {long_minutes}; caching, splitting, or a larger runner pays back", path, {"medianMinutes": med, "limit": long_minutes}))
        if p["minutes"] and p["failedMinutes"] / p["minutes"] >= 0.2:
            out.append(finding("actions-cost/failed-minutes", "info", f"{path}: {p['failedMinutes']} of {p['minutes']} minute(s) went to runs that failed or were cancelled", path, {"failedMinutes": p["failedMinutes"], "minutes": p["minutes"]}))
        if p["rerunMinutes"]:
            out.append(finding("actions-cost/reruns", "info", f"{path}: {p['rerunMinutes']} minute(s) on re-run attempts", path, {"rerunMinutes": p["rerunMinutes"]}))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda x: (order[x["level"]], x["ruleId"], x["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "github-actions-cost-audit", "version": "0.1.0"},
                                         "properties": {"since": since.isoformat().replace("+00:00", "Z"), "asOf": as_of.isoformat().replace("+00:00", "Z"),
                                                        "runs": sum(p["runs"] for p in per_wf.values()), "minutes": total_minutes, "weightedMinutes": weighted_total,
                                                        "workflows": {k: {"runs": v["runs"], "minutes": v["minutes"], "weightedMinutes": v["weighted"]} for k, v in sorted(per_wf.items())},
                                                        "approximation": "wall-clock per run x runner multiplier; billing is per job"}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
