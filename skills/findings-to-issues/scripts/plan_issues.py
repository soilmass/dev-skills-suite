#!/usr/bin/env python3
"""Plan GitHub issues for the findings an audit produced, as a plan-doc
(kit/shapes/plan-doc.schema.json).

Usage:
    plan_issues.py <repo-path> <finding-list.json>... [--min-level warning|error] [--label L] [--limit N]
    plan_issues.py <repo-path> <finding-list.json>... --issues-json-file <path> [--min-level …] [--label L]

This is the deterministic part of findings-to-issues' Decide stage
(SDS-C-060). Findings at or above --min-level (default warning) are
grouped by (tool, ruleId); each group becomes one proposed issue whose
body lists every location. A group already open — an open issue whose
body carries the marker `<!-- sds-finding-group: <tool>/<ruleId> -->`
is skipped, which is what makes a re-run a no-op (SDS-C-004). Live
mode reads (rung 3):
    gh issue list --state open --limit 200 --json number,title,body,labels
`--issues-json-file` (SDS-S-065) replaces it with a file in the same
array shape. The creations are direct, gated tool calls outside this
script (SDS-S-051); it never writes to GitHub.

Prints one plan-doc; nothing to file yields a single 'nothing to do'
phase (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that
is not a directory (repo-invalid), an input that is not a finding-list
(findings-invalid), an issues file that is not a JSON array
(issues-unparseable), a bad level (level-invalid), or a failed live
call (gh-unreachable).
"""
import json, re, subprocess, sys
from collections import OrderedDict
from pathlib import Path

MARK = "<!-- sds-finding-group: {} -->"
LEVELS = {"note": 0, "info": 0, "warning": 1, "error": 2}


def load_findings(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        runs = doc["runs"]
        assert isinstance(runs, list)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: {path} is not a finding-list (findings-invalid): {e}")
    for run in runs:
        tool = run.get("tool", {}).get("driver", {}).get("name", "unknown")
        for r in run.get("results", []):
            loc = (r.get("locations") or [{}])[0].get("physicalLocation", {})
            uri = loc.get("artifactLocation", {}).get("uri", "(no location)")
            line = loc.get("region", {}).get("startLine")
            yield tool, r["ruleId"], str(r.get("level", "warning")).lower(), r.get("message", {}).get("text", ""), uri, line


def load_issues(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert isinstance(data, list)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: issues file {path} is not a JSON array (issues-unparseable): {e}")
    return data


def live_issues(repo):
    try:
        r = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", "200", "--json", "number,title,body,labels"],
                           cwd=repo, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        sys.exit("ERROR: gh issue list timed out after 60s (gh-unreachable)")
    if r.returncode != 0:
        sys.exit(f"ERROR: gh issue list failed (gh-unreachable): {r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: gh returned unparseable JSON (issues-unparseable): {e}")


def main():
    args = sys.argv[1:]
    opts = {"--issues-json-file": None, "--min-level": "warning", "--label": "audit", "--limit": "20"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) < 2:
        sys.exit("ERROR: usage: plan_issues.py <repo-path> <finding-list.json>... [--issues-json-file F] [--min-level warning|error] [--label L] [--limit N]")
    repo, inputs = Path(args[0]), args[1:]
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    if opts["--min-level"] not in ("warning", "error"):
        sys.exit(f"ERROR: --min-level must be warning or error (level-invalid): {opts['--min-level']!r}")
    floor = LEVELS[opts["--min-level"]]
    limit = int(opts["--limit"])
    groups = OrderedDict()
    for path in inputs:
        for tool, rule, level, text, uri, line in load_findings(path):
            if LEVELS.get(level, 0) < floor:
                continue
            g = groups.setdefault((tool, rule), {"level": level, "locations": [], "text": text})
            g["locations"].append(f"{uri}:{line}" if line else uri)
            if LEVELS[level] > LEVELS[g["level"]]:
                g["level"] = level
    issues = load_issues(opts["--issues-json-file"]) if opts["--issues-json-file"] else live_issues(repo)
    open_marks = {m for i in issues for m in re.findall(r"<!-- sds-finding-group: (\S+) -->", i.get("body") or "")}
    steps, skipped = [], []
    for (tool, rule), g in list(groups.items())[:limit]:
        key = f"{tool}/{rule}"
        if key in open_marks:
            skipped.append(key)
            continue
        title = f"[{tool}] {rule}: {len(g['locations'])} location(s)"
        body = (f"{g['text']}\n\nLocations:\n" + "\n".join(f"- `{l}`" for l in sorted(set(g["locations"]))[:50])
                + f"\n\nSeverity: {g['level']}. Filed by findings-to-issues.\n{MARK.format(key)}")
        steps.append({"description": f"create issue {title!r} with label {opts['--label']}; body:\n{body}",
                      "riskIfFails": "low",
                      "rollback": "gh issue close <number> --reason 'not planned' — a rung-6 close, so a human runs it",
                      "checkpointAfter": True})
    goal = f"File {len(steps)} issue(s) for {len(groups)} finding group(s) at or above {opts['--min-level']} ({len(skipped)} already open, skipped)"
    phases = [{"name": "create", "steps": steps}] if steps else [{"name": "nothing to do", "steps": [
        {"description": f"every finding group is already open ({len(skipped)}) or nothing reached the floor", "riskIfFails": "low",
         "rollback": "none needed — nothing is written", "checkpointAfter": False}]}]
    print(json.dumps({"goal": goal, "phases": phases}, indent=2))


if __name__ == "__main__":
    main()
