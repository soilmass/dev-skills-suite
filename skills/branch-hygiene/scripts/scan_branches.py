#!/usr/bin/env python3
"""Scan a repository's branches and report the ones a human may want
to delete, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    scan_branches.py <repo-path> [--base <ref>] [--stale-days N]
                     [--as-of YYYY-MM-DD]
    scan_branches.py <repo-path> --facts-file <branches.json>
                     [--stale-days N] [--as-of YYYY-MM-DD]

Reads only local refs (rung 2, domain-read-only): `git for-each-ref`
over refs/heads, `git branch --merged <base>`, and each branch's
upstream tracking state. It never fetches, prunes, or deletes — a
branch deletion is a rung-6 act reserved for a human with the
finding in hand (SDS-S-023).

Detectors (deterministic; whether a branch should actually go is the
skill's Analyze stage):
    branch/merged        merged into <base> and not <base> itself
                         -> info   ("safe to delete: history is on base")
    branch/stale         last commit older than --stale-days (default
                         30) and NOT merged -> warning
    branch/gone-upstream tracks an upstream ref that no longer exists
                         -> info   ("remote branch was deleted")
A branch can carry more than one finding.

Staleness depends on "today", which is ambient state a hermetic Gather
must not read silently (SDS-C-003): pass --as-of to fix the reference
date; without it the script uses the current date and says so in each
stale finding's message. --facts-file (SDS-S-065) substitutes a JSON
array of {"name", "lastCommit" (ISO date), "merged" (bool),
"upstream" (str|null), "upstreamGone" (bool)} for the git calls.

Prints one finding-list. A repository with only the base branch, or
nothing stale/merged/gone, yields an empty `results` array
(SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that is not
a git repository root (repo-invalid), an unreadable/malformed facts
file (facts-unparseable), or a non-integer --stale-days / bad --as-of
(bad-argument).
"""
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path


def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def gather(repo, base):
    try:
        top = git(repo, "rev-parse", "--show-toplevel").strip()
    except RuntimeError as e:
        sys.exit(f"ERROR: not a git repository (repo-invalid): {repo}: {e}")
    if Path(top).resolve() != Path(repo).resolve():
        sys.exit(f"ERROR: not a git repository root (repo-invalid): {repo} (root is {top})")
    merged = {l.strip().lstrip("* ").strip() for l in git(repo, "branch", "--merged", base, "--format=%(refname:short)").splitlines() if l.strip()}
    facts = []
    fmt = "%(refname:short)|%(committerdate:short)|%(upstream:short)|%(upstream:track)"
    for line in git(repo, "for-each-ref", f"--format={fmt}", "refs/heads").splitlines():
        name, day, upstream, track = (line.split("|") + ["", "", ""])[:4]
        facts.append({
            "name": name, "lastCommit": day, "merged": name in merged,
            "upstream": upstream or None, "upstreamGone": track.strip() == "[gone]",
        })
    return facts


def load_facts(path):
    try:
        facts = json.loads(Path(path).read_text())
        assert isinstance(facts, list) and all({"name", "lastCommit", "merged"} <= set(f) for f in facts)
    except (OSError, json.JSONDecodeError, AssertionError, TypeError) as e:
        sys.exit(f"ERROR: could not read branch facts {path} (facts-unparseable): {e}")
    return facts


def finding(rule, level, text, name, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": f"refs/heads/{name}"}}}],
            "properties": props}


def main():
    args = sys.argv[1:]
    def take(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value (bad-argument)")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    base = take("--base", "main")
    facts_file = take("--facts-file")
    stale_days = take("--stale-days", "30")
    as_of = take("--as-of")
    if len(args) != 1:
        sys.exit("ERROR: usage: scan_branches.py <repo-path> [--base <ref>] [--stale-days N] [--as-of YYYY-MM-DD] [--facts-file <json>]")
    try:
        stale_days = int(stale_days)
        today = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError as e:
        sys.exit(f"ERROR: --stale-days must be an integer and --as-of a YYYY-MM-DD date (bad-argument): {e}")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")

    facts = load_facts(facts_file) if facts_file else gather(repo, base)
    base_short = base.split("/")[-1]
    results = []
    for f in sorted(facts, key=lambda x: x["name"]):
        name = f["name"]
        if name in (base, base_short):
            continue
        try:
            age = (today - date.fromisoformat(f["lastCommit"][:10])).days
        except ValueError:
            sys.exit(f"ERROR: bad lastCommit date for {name!r} (facts-unparseable): {f['lastCommit']!r}")
        props = {"branch": name, "lastCommit": f["lastCommit"][:10], "ageDays": age,
                 "merged": bool(f["merged"]), "upstream": f.get("upstream")}
        if f["merged"]:
            results.append(finding("branch/merged", "info", f"{name} is merged into {base}: safe to delete, its history is on the base", name, props))
        elif age >= stale_days:
            ref = f"as of {today.isoformat()}" if as_of else f"as of today ({today.isoformat()}, ambient)"
            results.append(finding("branch/stale", "warning", f"{name} has no commits for {age} days ({ref}) and is not merged into {base}", name, props))
        if f.get("upstreamGone"):
            results.append(finding("branch/gone-upstream", "info", f"{name} tracks {f.get('upstream')}, which no longer exists on the remote", name, props))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["properties"]["branch"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "branch-hygiene", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
