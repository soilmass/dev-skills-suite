#!/usr/bin/env python3
"""Check a range of commit messages against Conventional Commits, as a
finding-list (kit/shapes/finding-list.schema.json).

Usage:
    lint_commits.py <repo-path> [--range <base>..<head>] [--types a,b] [--max-subject N]
    lint_commits.py <repo-path> --log-file <path> [--types a,b] [--max-subject N]

Effect Ladder rung 2 (domain-read-only) live: one `git log` over the
range (default: the commits on HEAD not on the default branch, via
`git log <default>..HEAD`). `--log-file` (SDS-S-065) substitutes a
file in the same record format changelog-writer records —
`%h<TAB>%s<TAB>%b<<END>>` per commit — so the two skills share one
recording and evals run without a repository.

Conventional Commits (conventionalcommits.org, 1.0.0) rules:

    commit/not-conventional     subject is not `type(scope)!: description`
                                -> warning (the changelog cannot classify it)
    commit/unknown-type         the type is not in --types (default:
                                feat, fix, docs, style, refactor, perf,
                                test, build, ci, chore, revert) -> info
    commit/breaking-no-footer   `!` in the subject but no
                                `BREAKING CHANGE:` / `BREAKING-CHANGE:`
                                footer -> warning (tools read the
                                footer; the bang is a hint)
    commit/subject-too-long     subject over --max-subject (default 72)
                                -> info
    commit/subject-style        description starts with a capital or
                                ends with a period -> info (the spec's
                                convention; tools concatenate them)
    commit/empty-description    `type:` with nothing after the colon
                                -> warning
    commit/fixup-left           a `fixup!` / `squash!` subject in the
                                range -> warning (autosquash never ran)

Merge commits (`Merge branch`, `Merge pull request`) are skipped.
Properties carry the hash, subject, and parsed parts. Deciding
whether a nonconformant message is worth a rewrite (the branch is
about to be squash-merged; the type is a team convention) is the
skill's Analyze stage (SDS-S-061).

Prints one finding-list; a clean range yields an empty `results`
array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that
is not a directory (repo-invalid), an unreadable log file
(log-unreadable), or a failed git command (git-failed).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_TYPES = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"]
SUBJECT_RE = re.compile(r"^(?P<type>[a-z][a-z0-9-]*)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<desc>.*)$")
FOOTER_RE = re.compile(r"^BREAKING[ -]CHANGE:", re.M)


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}], "properties": props}


def parse_log(text):
    commits = []
    for rec in text.split("<<END>>"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split("\t", 2)
        if len(parts) < 2:
            continue
        commits.append({"hash": parts[0].strip(), "subject": parts[1].strip(), "body": parts[2] if len(parts) > 2 else ""})
    return commits


def live_log(repo, rng):
    if not rng:
        r = subprocess.run(["git", "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], cwd=repo, capture_output=True, text=True)
        default = r.stdout.strip() or "main"
        rng = f"{default}..HEAD"
    r = subprocess.run(["git", "log", "--format=%h%x09%s%x09%b<<END>>", rng], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: git log {rng} failed (git-failed): {r.stderr.strip()}")
    return parse_log(r.stdout), rng


def main():
    args = sys.argv[1:]
    opts = {"--range": None, "--log-file": None, "--types": None, "--max-subject": "72"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: lint_commits.py <repo-path> [--range A..B | --log-file F] [--types a,b] [--max-subject N]")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    types = [t.strip() for t in opts["--types"].split(",")] if opts["--types"] else DEFAULT_TYPES
    try:
        max_subject = int(opts["--max-subject"])
    except ValueError:
        sys.exit("ERROR: --max-subject must be an integer (git-failed)")
    if opts["--log-file"]:
        try:
            commits, source = parse_log(Path(opts["--log-file"]).read_text(encoding="utf-8")), f"log-file:{Path(opts['--log-file']).name}"
        except (OSError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: could not read log file {opts['--log-file']} (log-unreadable): {e}")
    else:
        commits, source = live_log(repo, opts["--range"])
    out, skipped = [], 0
    for c in commits:
        uri, subject = c["hash"], c["subject"]
        if subject.startswith(("Merge branch", "Merge pull request", "Merge remote-tracking")):
            skipped += 1
            continue
        if re.match(r"^(fixup|squash)! ", subject):
            out.append(finding("commit/fixup-left", "warning", f"{uri}: {subject[:60]!r} is an autosquash marker; rebase --autosquash never ran", uri, {"hash": uri, "subject": subject}))
            continue
        m = SUBJECT_RE.match(subject)
        if not m:
            out.append(finding("commit/not-conventional", "warning", f"{uri}: {subject[:60]!r} is not `type(scope)!: description`", uri, {"hash": uri, "subject": subject}))
            continue
        t, desc, bang = m.group("type"), m.group("desc"), bool(m.group("bang"))
        props = {"hash": uri, "subject": subject, "type": t, "scope": m.group("scope"), "breaking": bang}
        if t not in types:
            out.append(finding("commit/unknown-type", "info", f"{uri}: type {t!r} is not one of {', '.join(types)}", uri, props))
        if not desc.strip():
            out.append(finding("commit/empty-description", "warning", f"{uri}: nothing after the colon", uri, props))
        if bang and not FOOTER_RE.search(c["body"]):
            out.append(finding("commit/breaking-no-footer", "warning", f"{uri}: marked breaking with `!` but no BREAKING CHANGE: footer explains what breaks", uri, props))
        if len(subject) > max_subject:
            out.append(finding("commit/subject-too-long", "info", f"{uri}: subject is {len(subject)} characters (limit {max_subject})", uri, props))
        if desc[:1].isupper() or desc.rstrip().endswith("."):
            out.append(finding("commit/subject-style", "info", f"{uri}: description {'starts with a capital' if desc[:1].isupper() else 'ends with a period'}; the convention is lowercase, no period", uri, props))
    order = {"warning": 0, "info": 1}
    out.sort(key=lambda r: (order[r["level"]], r["properties"]["hash"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "commit-message-lint", "version": "0.1.0"},
                                         "properties": {"source": source, "commits": len(commits), "mergeCommitsSkipped": skipped,
                                                        "conventional": sum(1 for c in commits if SUBJECT_RE.match(c["subject"]))}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
