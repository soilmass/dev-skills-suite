#!/usr/bin/env python3
"""Collect the commits since the last tag and group them into Keep a
Changelog categories as a status-report (kit/shapes/status-report.schema.json).

Usage:
    collect_commits.py <repo-path> [--since <ref>] [--include-all]
    collect_commits.py <repo-path> --log-file <path> [--include-all]

Input convention is Conventional Commits (SDS-C-031, standards first):
    <type>[(scope)][!]: <subject>
    ...
    BREAKING CHANGE: <text>
Output convention is Keep a Changelog: one section per category, in
its canonical order — Added, Changed, Deprecated, Removed, Fixed,
Security — plus Uncategorized for commits that do not follow the
convention (they are never silently dropped).

Type mapping (deterministic; whether a line belongs in the release
notes for humans is the skill's Analyze stage, not this script's):
    feat                     -> Added
    fix                      -> Fixed
    perf, refactor, revert   -> Changed
    deprecate                -> Deprecated
    remove                   -> Removed
    security, or scope
      "security" on fix      -> Security
    chore, docs, test, ci,
      build, style           -> omitted (not user-facing) unless
                                --include-all, then Changed
A commit with "!" after the type/scope or a "BREAKING CHANGE:" footer
is prefixed "**BREAKING:**" inside its category.

Live mode reads `git log <since>..HEAD --format=%h%x09%s%x09%b<<END>>`
(rung 2, domain-read-only) — tab-separated hash, subject, body, each
record terminated by the literal `<<END>>` — where <since> defaults to
the most recent tag (`git describe --tags --abbrev=0`) or, with no
tags, the root. The `--log-file` flag (SDS-S-065) substitutes a file
in that exact format so evals run without a repository.

Prints one status-report: summary = counts per category; sections =
one per non-empty category, body = one "- <subject> (<hash>)" line per
commit; generatedFrom = the ref range. Zero commits -> a well-formed
status-report with an empty `sections` array (SDS-C-033). Exit 1 with
"ERROR: ..." on stderr for: not a git repository root (repo-invalid);
an unreadable log file (log-unreadable).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ORDER = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security", "Uncategorized"]
TYPE_MAP = {"feat": "Added", "fix": "Fixed", "perf": "Changed", "refactor": "Changed", "revert": "Changed",
            "deprecate": "Deprecated", "remove": "Removed", "security": "Security"}
OMIT = {"chore", "docs", "test", "ci", "build", "style"}
HEADER_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s+(?P<subject>.+)$")


def read_log(repo, since):
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.exit(f"ERROR: not a git repository (repo-invalid): {repo}: {e}")
    if Path(top).resolve() != Path(repo).resolve():
        sys.exit(f"ERROR: not a git repository root (repo-invalid): {repo} (root is {top})")
    if since is None:
        r = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], cwd=repo, capture_output=True, text=True)
        since = r.stdout.strip() if r.returncode == 0 else None
    rng = f"{since}..HEAD" if since else "HEAD"
    out = subprocess.run(["git", "log", rng, "--format=%h%x09%s%x09%b<<END>>"], cwd=repo, capture_output=True, text=True, check=True).stdout
    return out, rng


def parse(raw):
    commits = []
    for rec in raw.split("<<END>>"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split("\t")
        if len(parts) < 2:
            continue
        h, subject = parts[0].strip(), parts[1].strip()
        body = parts[2] if len(parts) > 2 else ""
        commits.append((h, subject, body))
    return commits


def categorize(commits, include_all):
    sections = {k: [] for k in ORDER}
    for h, subject, body in commits:
        m = HEADER_RE.match(subject)
        breaking = "BREAKING CHANGE:" in body or "BREAKING-CHANGE:" in body
        if not m:
            sections["Uncategorized"].append(f"- {subject} ({h})")
            continue
        t, scope, bang, text = m.group("type"), m.group("scope") or "", m.group("bang"), m.group("subject")
        breaking = breaking or bool(bang)
        if t in OMIT and not include_all:
            continue
        if t == "fix" and scope.lower() == "security":
            cat = "Security"
        else:
            cat = TYPE_MAP.get(t, "Changed" if include_all else None)
        if cat is None:
            sections["Uncategorized"].append(f"- {subject} ({h})")
            continue
        label = f"{scope}: " if scope else ""
        prefix = "**BREAKING:** " if breaking else ""
        sections[cat].append(f"- {prefix}{label}{text} ({h})")
    return sections


def main():
    args = sys.argv[1:]
    include_all = "--include-all" in args
    if include_all:
        args.remove("--include-all")
    def take(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None
    since = take("--since")
    log_file = take("--log-file")
    if len(args) != 1:
        sys.exit("ERROR: usage: collect_commits.py <repo-path> [--since <ref>] [--log-file <path>] [--include-all]")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")

    if log_file:
        try:
            raw = Path(log_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: could not read log file {log_file} (log-unreadable): {e}")
        rng = f"log-file:{log_file}"
    else:
        raw, rng = read_log(repo, since)

    sections = categorize(parse(raw), include_all)
    counts = {k: len(v) for k, v in sections.items() if v}
    report = {
        "summary": (", ".join(f"{n} {k.lower()}" for k, n in counts.items()) if counts else "no changes") + f" since {rng}",
        "sections": [{"heading": k, "body": "\n".join(sections[k])} for k in ORDER if sections[k]],
        "generatedFrom": rng,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
