#!/usr/bin/env python3
"""Analyze a history of JUnit XML test reports and emit a finding-list
of intermittent and consistently failing tests, with the evidence a
human (or the model's Analyze stage) needs to classify each one.

Usage:
    analyze_test_history.py <reports-dir> [--manifest <runs.json>]
                            [--git-root <repo>] [--recent-days N]

Input format is JUnit XML — the de facto interchange format every
test runner and CI system can emit (SDS-C-031, standards first). Each
<testcase classname name> with a <failure> or <error> child counts as
a failure for that run; <skipped> is ignored.

Runs are correlated by commit through an optional manifest (report
paths are relative to the manifest file's own directory):
    {"runs": [{"report": "reports/run-1.xml", "commit": "abc123",
               "timestamp": "2026-09-01T10:00:00Z"}, ...]}
Without a manifest every report is treated as the SAME commit
(conservative: it can only over-report intermittency, never hide it),
and a NOTE says so on stderr.

Detectors (deterministic; classification is NOT done here — SDS-S-061):
    flaky/intermittent        passed in some runs and failed in others
                              on the same commit -> warning
    flaky/consistent-failure  failed in every run it appears in
                              (2+ runs) -> error
Each finding carries properties: runs, failures, passRate,
failureMessages (distinct), and hints — mechanical observations only:
    "timing-like failure message"   message matches timeout/
                                    connection/socket/port/deadline
    "distinct failure messages"     failures do not share one message
    "test file changed recently"    with --git-root: the test's source
                                    file (derived from classname) has
                                    a commit within --recent-days
                                    (default 14) — domain-read-only

Prints one finding-list document. No reports, or no failures at all,
-> a well-formed document with an empty `results` array (SDS-C-033).
Exit 1 with "ERROR: ..." on stderr for: a reports path that is not a
directory (reports-missing); a report that is not well-formed XML
(report-unparseable); a manifest that is unreadable or malformed
(manifest-unparseable).
"""
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMING_RE = re.compile(r"timeout|timed out|connection|socket|port|deadline|ECONNREFUSED|EADDRINUSE|refused", re.I)


def load_manifest(path, reports_dir):
    """Report paths in the manifest are relative to the manifest's own
    directory, so a manifest can sit beside (not inside) reports/."""
    try:
        data = json.loads(Path(path).read_text())
        runs = data["runs"]
        base = Path(path).resolve().parent
        return {str((base / r["report"]).resolve()): r for r in runs}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        sys.exit(f"ERROR: could not read runs manifest {path} (manifest-unparseable): {e}")


def parse_report(path):
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        sys.exit(f"ERROR: {path} is not well-formed JUnit XML (report-unparseable): {e}")
    outcomes = {}
    for tc in tree.getroot().iter("testcase"):
        key = f"{tc.get('classname', '')}::{tc.get('name', '')}"
        if tc.find("skipped") is not None:
            continue
        fail = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        if fail is not None:
            msg = (fail.get("message") or (fail.text or "").strip().splitlines()[0:1] or [""])
            outcomes[key] = ("fail", msg if isinstance(msg, str) else msg[0])
        else:
            outcomes[key] = ("pass", None)
    return outcomes


def recent_change(git_root, classname, days):
    if not git_root:
        return None
    candidate = classname.replace(".", "/")
    for rel in (f"{candidate}.py", f"{candidate}.js", f"{candidate}.ts", f"{candidate}.go", f"{candidate}.java"):
        p = Path(git_root) / rel
        if p.exists():
            since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
            r = subprocess.run(["git", "log", "-1", "--since", since, "--format=%h", "--", rel],
                               cwd=git_root, capture_output=True, text=True)
            return bool(r.stdout.strip())
    return None


def main():
    args = sys.argv[1:]
    def take(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    manifest = take("--manifest")
    git_root = take("--git-root")
    recent_days = int(take("--recent-days", "14"))
    if len(args) != 1:
        sys.exit("ERROR: usage: analyze_test_history.py <reports-dir> [--manifest <runs.json>] [--git-root <repo>] [--recent-days N]")
    reports_dir = Path(args[0])
    if not reports_dir.is_dir():
        sys.exit(f"ERROR: reports path is not a directory (reports-missing): {reports_dir}")

    meta = load_manifest(manifest, reports_dir) if manifest else {}
    reports = sorted(reports_dir.glob("*.xml"))
    if reports and not manifest:
        print("NOTE: no --manifest given; treating all reports as the same commit", file=sys.stderr)

    # per test -> per commit -> list of (run, outcome, message)
    history = defaultdict(lambda: defaultdict(list))
    for rp in reports:
        commit = meta.get(str(rp.resolve()), {}).get("commit", "unknown")
        for key, (outcome, msg) in parse_report(rp).items():
            history[key][commit].append((rp.name, outcome, msg))

    results = []
    for key in sorted(history):
        classname, name = key.split("::", 1)
        for commit, runs in history[key].items():
            outcomes = [o for _, o, _ in runs]
            if len(runs) < 2 or "fail" not in outcomes:
                continue
            fails = [m for _, o, m in runs if o == "fail"]
            messages = sorted({m for m in fails if m})
            hints = []
            if any(TIMING_RE.search(m or "") for m in fails):
                hints.append("timing-like failure message")
            if len(messages) > 1:
                hints.append("distinct failure messages")
            changed = recent_change(git_root, classname, recent_days)
            if changed:
                hints.append("test file changed recently")
            intermittent = "pass" in outcomes
            rule = "flaky/intermittent" if intermittent else "flaky/consistent-failure"
            level = "warning" if intermittent else "error"
            pass_rate = round(outcomes.count("pass") / len(outcomes), 2)
            text = (f"{key} {'passed and failed' if intermittent else 'failed every run'} on commit {commit}: "
                    f"{outcomes.count('fail')}/{len(outcomes)} runs failed"
                    + (f"; hints: {', '.join(hints)}" if hints else ""))
            results.append({
                "ruleId": rule,
                "level": level,
                "message": {"text": text},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": classname.replace(".", "/") or "unknown"}}}],
                "properties": {
                    "test": key, "commit": commit, "runs": len(outcomes),
                    "failures": outcomes.count("fail"), "passRate": pass_rate,
                    "failureMessages": messages, "hints": hints,
                },
            })

    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{"tool": {"driver": {"name": "flaky-test-triage", "version": "0.1.0"}}, "results": results}],
    }, indent=2))


if __name__ == "__main__":
    main()
