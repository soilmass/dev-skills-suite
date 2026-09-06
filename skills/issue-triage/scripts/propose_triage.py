#!/usr/bin/env python3
"""Propose triage actions for untriaged GitHub issues, as a plan-doc
(kit/shapes/plan-doc.schema.json).

Usage:
    propose_triage.py <repo-path> [--limit N] [--as-of ISO] [--stale-days N]
    propose_triage.py <repo-path> --issues-json-file <path> --as-of ISO [--stale-days N]

This is the deterministic part of issue-triage's Decide stage
(SDS-C-060): a fixed rule table from issue facts to proposed labels
and comments. The model's Analyze stage revises the proposal — a
keyword rule can misread a title — before anything is applied, and
every application is a direct, gated tool call outside this script
(SDS-S-051). The script itself is Effect Ladder rung 3 in live mode
(one read) and rung 1 with a fixture; it never writes to GitHub.

Live mode reads:
    gh issue list --state open --limit N --json
        number,title,body,labels,createdAt,updatedAt,author,comments
`--issues-json-file` (SDS-S-065) replaces that call with a file in
the same shape (an array). `--as-of` injects the clock (SDS-S-064);
it is REQUIRED with a fixture.

Label taxonomy: assets/taxonomy.json — kind/*, priority/*, and the
triage marker `triaged`. An issue carrying any kind/* label is
considered triaged and skipped.

Rule table per untriaged issue:
    kind      title/body mention crash|error|exception|traceback|
              broken|fails|regression|bug          -> kind/bug
              feature|add support|would be nice|proposal|enhancement
                                                   -> kind/feature
              question mark in title, or how do i|how to|is it possible
                                                   -> kind/question
              docs|readme|documentation|typo       -> kind/docs
              otherwise                            -> kind/needs-info
                                                      + a comment asking
                                                      what the issue is
    priority  kind/bug and security|data loss|corrupt|crash|outage
                                                   -> priority/high
              kind/bug otherwise                   -> priority/normal
    repro     kind/bug with no "steps to reproduce"/"repro"/"expected"
              and body under 200 chars             -> comment asking
                                                      for reproduction
    stale     no update for --stale-days (default 90) and no comments
                                                   -> comment asking if
                                                      still relevant
Every step is one label or one comment on one issue, with its
rollback: a label is removed with `gh issue edit N --remove-label`;
a comment can only be deleted through `gh api -X DELETE`, which is
rung 6, so comment steps are sequenced after label steps.

Prints one plan-doc; with nothing to triage the plan has a single
"nothing to do" phase (SDS-C-033: a valid, empty plan). Exit 1 with
"ERROR: ..." on stderr for a path that is not a directory
(repo-invalid), a fixture that is not a JSON array of issues
(issues-unparseable), a missing or unparseable --as-of (as-of-invalid),
or a live call that fails (gh-unreachable).
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FIELDS = "number,title,body,labels,createdAt,updatedAt,author,comments"
BUG_RE = re.compile(r"\b(crash(es|ed)?|error|exception|traceback|broken|fails?|failing|regression|bug)\b", re.I)
FEATURE_RE = re.compile(r"\b(feature|add support|would be nice|proposal|enhancement|request(ing)?)\b", re.I)
QUESTION_RE = re.compile(r"\b(how do i|how to|is it possible|can i|why does)\b", re.I)
DOCS_RE = re.compile(r"\b(docs?|readme|documentation|typo)\b", re.I)
HIGH_RE = re.compile(r"\b(security|data loss|corrupt(ed|ion)?|crash(es|ed)?|outage|vulnerab)", re.I)
REPRO_RE = re.compile(r"(steps to reproduce|repro|expected|actual)", re.I)


def parse_ts(value, what):
    if not value:
        sys.exit(f"ERROR: {what} is required (as-of-invalid)")
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        sys.exit(f"ERROR: {what} {value!r} is not an ISO-8601 timestamp (as-of-invalid)")
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def load_taxonomy():
    return json.loads((Path(__file__).resolve().parent.parent / "assets" / "taxonomy.json").read_text(encoding="utf-8"))


def load_fixture(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load issues file {path} (issues-unparseable): {e}")
    if not isinstance(data, list) or not all(isinstance(i, dict) and "number" in i for i in data):
        sys.exit(f"ERROR: issues file {path} must be a JSON array of issue objects with numbers (issues-unparseable)")
    return data


def load_live(repo, limit):
    result = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", str(limit), "--json", FIELDS],
                            cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"ERROR: gh issue list failed (gh-unreachable): {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: gh issue list returned unparseable JSON (issues-unparseable): {e}")


def classify(issue):
    text = f"{issue.get('title', '')}\n{issue.get('body') or ''}"
    title = issue.get("title", "")
    if BUG_RE.search(text):
        return "bug"
    if FEATURE_RE.search(text):
        return "feature"
    if title.strip().endswith("?") or QUESTION_RE.search(text):
        return "question"
    if DOCS_RE.search(text):
        return "docs"
    return "needs-info"


def propose(issues, as_of, stale_days, taxonomy):
    kinds = set(taxonomy["kind"])
    label_steps, comment_steps, skipped = [], [], []
    for issue in sorted(issues, key=lambda i: i["number"]):
        n = issue["number"]
        labels = {l["name"] if isinstance(l, dict) else str(l) for l in issue.get("labels") or []}
        if labels & {f"kind/{k}" for k in kinds} or "triaged" in labels:
            skipped.append(n)
            continue
        kind = classify(issue)
        body = issue.get("body") or ""
        text = f"{issue.get('title', '')}\n{body}"
        def label(name, why):
            label_steps.append({"description": f"add label {name} to #{n}: {why}", "riskIfFails": "low",
                                "rollback": f"gh issue edit {n} --remove-label {name}", "checkpointAfter": True,
                                "issue": n, "action": "label", "label": name})
        def comment(text_, why):
            comment_steps.append({"description": f"comment on #{n} ({why}): {text_}", "riskIfFails": "low",
                                  "rollback": "delete the comment with gh api -X DELETE /repos/{owner}/{repo}/issues/comments/<id> — a rung-6 call, so this step is sequenced last",
                                  "checkpointAfter": True, "issue": n, "action": "comment", "body": text_})
        label(f"kind/{kind}", f"title/body match the {kind} rule")
        if kind == "bug":
            label("priority/high" if HIGH_RE.search(text) else "priority/normal",
                  "bug mentions " + ("a high-severity term" if HIGH_RE.search(text) else "no high-severity term"))
            if not REPRO_RE.search(body) and len(body) < 200:
                comment("Thanks for the report. Could you add the steps to reproduce, what you expected, and what happened instead? That lets us confirm it quickly.", "bug without reproduction")
        if kind == "needs-info":
            comment("Thanks for opening this. Could you say whether it is a bug, a feature request, or a question, and what you would like to see happen?", "kind unclear")
        updated = parse_ts(issue.get("updatedAt") or issue.get("createdAt"), f"#{n} updatedAt")
        if (as_of - updated).days >= stale_days and not (issue.get("comments") or []):
            comment(f"This has had no activity for {(as_of - updated).days} days. Is it still relevant? If we do not hear back it may be closed.", "stale")
    phases = []
    if label_steps:
        phases.append({"name": "label", "steps": label_steps})
    if comment_steps:
        phases.append({"name": "comment", "steps": comment_steps})
    if not phases:
        phases.append({"name": "nothing to do", "steps": [{"description": f"no untriaged open issues as of {as_of.isoformat()}; {len(skipped)} already triaged", "riskIfFails": "low", "rollback": "none needed: no action is taken", "checkpointAfter": False}]})
    return {"goal": f"Triage {len(issues) - len(skipped)} untriaged open issue(s) as of {as_of.date().isoformat()} ({len(skipped)} already triaged, skipped)",
            "phases": phases}


def main():
    args = sys.argv[1:]
    opts = {"--limit": "100", "--as-of": None, "--stale-days": "90", "--issues-json-file": None}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: propose_triage.py <repo-path> [--limit N] [--issues-json-file F] --as-of ISO [--stale-days N]")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    try:
        stale_days = int(opts["--stale-days"])
    except ValueError:
        sys.exit("ERROR: --stale-days must be an integer (as-of-invalid)")
    if opts["--issues-json-file"]:
        as_of = parse_ts(opts["--as-of"], "--as-of (required with --issues-json-file)")
        issues = load_fixture(opts["--issues-json-file"])
    else:
        as_of = parse_ts(opts["--as-of"], "--as-of") if opts["--as-of"] else datetime.now(timezone.utc)
        issues = load_live(repo, opts["--limit"])
    print(json.dumps(propose(issues, as_of, stale_days, load_taxonomy()), indent=2))


if __name__ == "__main__":
    main()
