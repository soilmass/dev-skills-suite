#!/usr/bin/env python3
"""Decide whether a release can be published, and render the notes body
it would carry, as a decision-doc (kit/shapes/decision-doc.schema.json).

Usage:
    assess_release_readiness.py <repo-path> --version <tag> --notes-file <status-report.json>
        [--ci-decision-file <decision-doc.json>] [--as-of ISO]
    assess_release_readiness.py <repo-path> --version <tag> --notes-file <status-report.json>
        --release-json-file <facts.json> [--ci-decision-file <decision-doc.json>] --as-of ISO

This is the deterministic policy behind release-publisher's Decide
stage (SDS-C-060). Inputs are two upstream artifacts and a few facts
read from git and GitHub; the mapping to a chosen option is the rule
table below, so it lives in a script (SDS-S-060).

Inputs:
    --notes-file        the status-report release-notes-writer produced
                        (sections in impact order; `needsReview` lists
                        withheld commits)
    --ci-decision-file  the decision-doc ci-status-gate produced for the
                        commit being released (optional; without it the
                        decision says CI was not consulted)
Live mode reads (rung 3, read-only):
    gh release view <tag> --json tagName,isDraft,publishedAt,url
    git rev-parse -q --verify refs/tags/<tag> ; git rev-parse HEAD
`--release-json-file` (SDS-S-065) replaces both with a file of shape
{"release": {...}|null, "tag": {"exists": bool, "sha": str|null},
"head": str}. `--as-of` injects the clock (SDS-S-064) and is REQUIRED
with a fixture.

Rule table (first match wins):
    release exists and is not a draft         -> already-published
    release exists as a draft                 -> finalize-draft
    notes have no sections                    -> fix-notes
    notes.needsReview is non-empty            -> hold-for-review
    notes.summary does not start with version -> notes-mismatch
    ci decision given and chosenOption == wait-> wait-for-ci
    ci decision given and chosenOption == fail-> fix-ci
    otherwise                                 -> publish

`facts` carries the tag state, HEAD, whether the tag would be created
by the release, and `body`, the markdown rendered from the notes'
sections for `gh release create --notes-file`. Nothing is written.

Exit 1 with "ERROR: ..." on stderr for a path that is not a directory
(repo-invalid), a version that is not semver (version-invalid), a notes
file that is not a status-report (notes-unparseable), a CI decision
file that is not a decision-doc (ci-decision-unparseable), a fixture
that does not parse (release-state-unparseable), a missing --as-of
with a fixture (as-of-invalid), or a failed live call (gh-unreachable).
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SEMVER_RE = re.compile(r"^v?(\d+\.\d+\.\d+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
OPTIONS = ["publish", "already-published", "finalize-draft", "fix-notes", "hold-for-review", "notes-mismatch", "wait-for-ci", "fix-ci"]


def load_json(path, code, required_keys):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load {path} ({code}): {e}")
    if not isinstance(data, dict) or not all(k in data for k in required_keys):
        sys.exit(f"ERROR: {path} must be an object with {', '.join(required_keys)} ({code})")
    return data


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def load_live(repo, tag):
    code, out, err = run(["gh", "release", "view", tag, "--json", "tagName,isDraft,publishedAt,url"], repo)
    if code != 0:
        if "release not found" in err.lower() or "not found" in err.lower():
            release = None
        else:
            sys.exit(f"ERROR: gh release view failed (gh-unreachable): {err}")
    else:
        try:
            release = json.loads(out)
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: gh release view returned unparseable JSON (release-state-unparseable): {e}")
    code, sha, _ = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"], repo)
    tag_facts = {"exists": code == 0, "sha": sha if code == 0 else None}
    code, head, err = run(["git", "rev-parse", "HEAD"], repo)
    if code != 0:
        sys.exit(f"ERROR: git rev-parse HEAD failed (gh-unreachable): {err}")
    return {"release": release, "tag": tag_facts, "head": head}


def render_body(notes):
    parts = []
    for s in notes.get("sections", []):
        parts.append(f"## {s['heading']}\n\n{s['body'].rstrip()}\n")
    return "\n".join(parts).rstrip() + "\n" if parts else ""


def decide(tag, notes, ci, state, as_of):
    version = SEMVER_RE.match(tag).group(1)
    release = state.get("release")
    drivers = [f"tag {tag}: {'exists at ' + str(state['tag'].get('sha')) if state['tag'].get('exists') else 'will be created at HEAD ' + str(state.get('head'))}"]
    if release:
        drivers.append(f"release: exists ({'draft' if release.get('isDraft') else 'published ' + str(release.get('publishedAt'))}) {release.get('url', '')}".rstrip())
        chosen, why = ("finalize-draft", f"a draft release for {tag} already exists; finalize it rather than creating a second") if release.get("isDraft") else ("already-published", f"{tag} was published at {release.get('publishedAt')}; nothing to do")
    else:
        drivers.append("release: none")
        sections = notes.get("sections", [])
        review = notes.get("needsReview") or []
        drivers.append(f"notes: {len(sections)} section(s), {len(review)} withheld commit(s), summary {notes.get('summary', '')[:60]!r}")
        if ci:
            drivers.append(f"ci-status-gate: {ci['decisionOutcome']['chosenOption']} — {ci['decisionOutcome']['justification']}")
        else:
            drivers.append("ci-status-gate: not consulted")
        if not sections:
            chosen, why = "fix-notes", "the release notes have no sections; there is nothing to tell users"
        elif review:
            chosen, why = "hold-for-review", f"{len(review)} commit(s) were withheld from the notes for review; publish after they are classified or dropped"
        elif not re.match(rf"^\S+\s+v?{re.escape(version)}\b", notes.get("summary", "")) and not notes.get("summary", "").startswith(("v" + version, version)):
            chosen, why = "notes-mismatch", f"the notes' summary {notes.get('summary', '')[:40]!r} does not name version {version}; they may belong to another release"
        elif ci and ci["decisionOutcome"]["chosenOption"] == "wait":
            chosen, why = "wait-for-ci", "ci-status-gate says a required check is still running"
        elif ci and ci["decisionOutcome"]["chosenOption"] == "fail":
            chosen, why = "fix-ci", "ci-status-gate says a required check failed or is missing"
        else:
            chosen, why = "publish", f"no release for {tag} exists, the notes are complete and name {version}, and CI {'passed' if ci else 'was not consulted (say so in the gate)'}"
    return {
        "status": "accepted",
        "contextAndProblemStatement": f"Should {tag} be published as a GitHub release as of {as_of.isoformat()}?",
        "decisionDrivers": drivers,
        "consideredOptions": OPTIONS,
        "decisionOutcome": {"chosenOption": chosen, "justification": why},
        "consequences": {"positive": ["users are notified and the tag is fixed"] if chosen == "publish" else [],
                         "negative": ["a published release cannot be un-notified; deleting it leaves the tag and the emails"] if chosen == "publish" else []},
        "confirmation": "Re-run this assessment immediately before gh release create; a release or tag may have appeared meanwhile.",
        "facts": {"tag": tag, "version": version, "tagExists": bool(state["tag"].get("exists")), "tagSha": state["tag"].get("sha"),
                  "head": state.get("head"), "draftExists": bool(release and release.get("isDraft")),
                  "ciConsulted": bool(ci), "body": render_body(notes)},
    }


def main():
    args = sys.argv[1:]
    opts = {"--version": None, "--notes-file": None, "--ci-decision-file": None, "--release-json-file": None, "--as-of": None}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or not opts["--version"] or not opts["--notes-file"]:
        sys.exit("ERROR: usage: assess_release_readiness.py <repo-path> --version <tag> --notes-file <status-report.json> [--ci-decision-file F] [--release-json-file F] [--as-of ISO]")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    tag = opts["--version"]
    if not SEMVER_RE.match(tag):
        sys.exit(f"ERROR: version {tag!r} is not semver (vMAJOR.MINOR.PATCH[-prerelease]) (version-invalid)")
    notes = load_json(opts["--notes-file"], "notes-unparseable", ["summary", "sections"])
    ci = load_json(opts["--ci-decision-file"], "ci-decision-unparseable", ["decisionOutcome"]) if opts["--ci-decision-file"] else None
    if opts["--release-json-file"]:
        if not opts["--as-of"]:
            sys.exit("ERROR: --as-of is required with --release-json-file (as-of-invalid)")
        state = load_json(opts["--release-json-file"], "release-state-unparseable", ["release", "tag", "head"])
    else:
        state = load_live(repo, tag)
    try:
        as_of = datetime.fromisoformat(opts["--as-of"].replace("Z", "+00:00")) if opts["--as-of"] else datetime.now(timezone.utc)
    except ValueError:
        sys.exit(f"ERROR: --as-of {opts['--as-of']!r} is not an ISO-8601 timestamp (as-of-invalid)")
    print(json.dumps(decide(tag, notes, ci, state, as_of), indent=2))


if __name__ == "__main__":
    main()
