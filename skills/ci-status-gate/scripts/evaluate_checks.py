#!/usr/bin/env python3
"""Decide whether a commit's CI checks pass a gate, as a decision-doc
(kit/shapes/decision-doc.schema.json).

Usage:
    evaluate_checks.py <repo-path> [--ref <sha|branch>] [--required a,b] [--stale-minutes N] [--as-of ISO]
    evaluate_checks.py <repo-path> --checks-json-file <path> [--required a,b] [--stale-minutes N] --as-of ISO

This is the deterministic policy behind ci-status-gate's Analyze
stage (SDS-C-060). Every input is a fact read from GitHub's check-runs
API and the mapping to a chosen option is the fixed rule table below,
so it passes the toil test (SDS-S-060) and lives in a script.

Live mode reads (Effect Ladder rung 3, read-only):
    gh api -X GET repos/{owner}/{repo}/commits/<ref>/check-runs
and, when --required is not given, the branch protection's required
checks are NOT consulted (that needs admin scope); with no --required
every check found is treated as required.

`--checks-json-file` is the injectable-fixture flag (SDS-S-065): a file
in the check-runs API shape {"check_runs": [{name, status,
conclusion, started_at, completed_at, html_url}]} replaces the live
call. `--as-of` injects the clock (SDS-S-064) for staleness; it is
REQUIRED with a fixture and defaults to now in live mode.

Rule table (first match wins):
    a required check is absent from the run set       -> fail   (missing)
    a required check concluded failure/cancelled/
      timed_out/action_required/startup_failure       -> fail   (failed)
    a required check is queued/in_progress and has
      run longer than --stale-minutes (default 60)    -> fail   (stale)
    a required check is queued/in_progress            -> wait
    otherwise (success/neutral/skipped)               -> pass
    no check runs at all and no --required            -> no-checks (there
                                                         is no CI to gate on;
                                                         distinct from wait)
Non-required checks never change the outcome; a failing one is
listed under consequences.negative so the reader sees it.

Prints one decision-doc; an empty check-runs set with no --required
is a valid `no-checks` decision, not an error (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that is
not a directory (repo-invalid), a fixture that does not parse or lacks
check_runs (checks-unparseable), a missing --as-of with a fixture or
an unparseable timestamp (as-of-invalid), or a live call that fails
(gh-unreachable).
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FAILED = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
PENDING = {"queued", "in_progress", "waiting", "requested", "pending"}
OPTIONS = ["pass", "wait", "fail", "no-checks"]


def parse_ts(value, what):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        sys.exit(f"ERROR: {what} {value!r} is not an ISO-8601 timestamp (as-of-invalid)")


def load_fixture(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load checks file {path} (checks-unparseable): {e}")
    if not isinstance(data, dict) or not isinstance(data.get("check_runs"), list):
        sys.exit(f"ERROR: checks file {path} must be an object with a check_runs array (checks-unparseable)")
    return data["check_runs"]


def load_live(repo, ref):
    result = subprocess.run(["gh", "api", "-X", "GET", f"repos/{{owner}}/{{repo}}/commits/{ref}/check-runs", "--paginate"],
                            cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"ERROR: gh api check-runs failed (gh-unreachable): {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: gh api returned unparseable JSON (checks-unparseable): {e}")
    return data.get("check_runs", [])


def decide(runs, required, stale_minutes, as_of):
    by_name = {}
    for r in runs:
        name = r.get("name", "")
        # keep the latest run per name (reruns share a name)
        if name not in by_name or (r.get("started_at") or "") > (by_name[name].get("started_at") or ""):
            by_name[name] = r
    req = list(required) if required else sorted(by_name)
    drivers, negative, positive = [], [], []
    verdict, reason = "pass", None
    for name in req:
        r = by_name.get(name)
        if r is None:
            verdict, reason = "fail", f"required check {name!r} has not reported at all"
            drivers.append(f"{name}: missing")
            break
        status, concl = (r.get("status") or "").lower(), (r.get("conclusion") or "").lower()
        if concl in FAILED:
            verdict, reason = "fail", f"required check {name!r} concluded {concl}"
            drivers.append(f"{name}: {concl}" + (f" — {r['html_url']}" if r.get("html_url") else ""))
            break
        if status in PENDING or (status != "completed" and not concl):
            started = parse_ts(r.get("started_at"), "started_at")
            age = (as_of - started).total_seconds() / 60 if started else None
            if age is not None and age > stale_minutes:
                verdict, reason = "fail", f"required check {name!r} has been {status} for {age:.0f} minutes (stale after {stale_minutes})"
                drivers.append(f"{name}: {status} for {age:.0f} min")
                break
            verdict = "wait"
            reason = f"required check {name!r} is {status}" + (f" ({age:.0f} min so far)" if age is not None else "")
            drivers.append(f"{name}: {status}")
            continue
        drivers.append(f"{name}: {concl or status}")
        positive.append(f"{name} {concl or status}")
    if verdict == "pass":
        reason = f"all {len(req)} required check(s) concluded successfully" if req else "no checks have reported and none are required; nothing gates this ref"
        if not req:
            verdict, reason = "no-checks", "no check runs exist for this ref and no required set was given; there is no CI to gate on — say so rather than wait"
    for name, r in sorted(by_name.items()):
        if name not in req and (r.get("conclusion") or "").lower() in FAILED:
            negative.append(f"non-required check {name!r} concluded {r['conclusion']}; it does not gate but someone should look")
    return {
        "status": "accepted",
        "contextAndProblemStatement": f"Should this ref pass the CI gate? {len(by_name)} check run(s) reported; required: {', '.join(req) or 'none given'}.",
        "decisionDrivers": drivers,
        "consideredOptions": OPTIONS,
        "decisionOutcome": {"chosenOption": verdict, "justification": reason},
        "consequences": {"positive": positive, "negative": negative},
        "confirmation": "Re-run this evaluation immediately before acting on it; check runs can be re-triggered and superseded.",
    }


def main():
    args = sys.argv[1:]
    opts = {"--ref": "HEAD", "--checks-json-file": None, "--required": None, "--stale-minutes": "60", "--as-of": None}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: evaluate_checks.py <repo-path> [--ref R] [--checks-json-file F] [--required a,b] [--stale-minutes N] [--as-of ISO]")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    try:
        stale = int(opts["--stale-minutes"])
    except ValueError:
        sys.exit("ERROR: --stale-minutes must be an integer (as-of-invalid)")
    required = [x.strip() for x in opts["--required"].split(",") if x.strip()] if opts["--required"] else None
    if opts["--checks-json-file"]:
        if not opts["--as-of"]:
            sys.exit("ERROR: --as-of is required with --checks-json-file so staleness is reproducible (as-of-invalid)")
        runs = load_fixture(opts["--checks-json-file"])
    else:
        runs = load_live(repo, opts["--ref"])
    as_of = parse_ts(opts["--as-of"], "--as-of") if opts["--as-of"] else datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    print(json.dumps(decide(runs, required, stale, as_of), indent=2))


if __name__ == "__main__":
    main()
