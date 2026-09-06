#!/usr/bin/env python3
"""Assess whether the current branch's pull request is ready to merge,
and emit that assessment as a decision-doc (kit/shapes/decision-doc.schema.json).

Usage:
    assess_pr_readiness.py <repo-path> [--pr <number>]
    assess_pr_readiness.py <repo-path> --pr-json-file <path>

This is the deterministic policy behind pr-lifecycle-manager's Decide
stage. Per SDS-C-060 (functional core, imperative shell) the
orchestrator holds no readiness judgment of its own: every input here
is a fact read from GitHub, and the mapping from facts to a chosen
option is a fixed rule table (below), so it passes the toil test
(SDS-S-060) and belongs in a script rather than in prose.

Live mode reads:
    gh pr view [<number>] --json number,state,isDraft,mergeable,
        mergeStateStatus,reviewDecision,statusCheckRollup,baseRefName,
        headRefName,title,url
    gh repo view --json mergeCommitAllowed,squashMergeAllowed,
        rebaseMergeAllowed,deleteBranchOnMerge
"gh pr view" reporting no pull request for the branch is NOT an error:
`pr` is null and the chosen option is `open-pr`.

`--pr-json-file` is the injectable-fixture flag (SDS-S-065): it
substitutes a file of shape {"pr": {...}|null, "repo": {...}} for both
live calls, so evals exercise this exact code path offline
(SDS-S-092).

Rule table (first match wins):
    pr is null                         -> open-pr
    state == MERGED                    -> already-merged
    state == CLOSED                    -> closed
    isDraft                            -> mark-ready
    mergeable == CONFLICTING           -> resolve-conflicts
    any check FAILURE/ERROR/CANCELLED  -> fix-failing-checks
    any check pending/in progress      -> wait-for-checks
    reviewDecision == CHANGES_REQUESTED-> address-review
    reviewDecision == REVIEW_REQUIRED  -> request-review
    otherwise (APPROVED, or "" meaning -> merge  (strategy: squash if
      no branch-protection rule requires   allowed, else merge, else
      a review; recorded as a driver)      rebase)

GitHub sets reviewDecision to "" when no protection rule requires a
review and none was given, and to REVIEW_REQUIRED when one is required
and absent. Only the latter blocks; the former is recorded in
decisionDrivers as "no review required by branch protection" so the
Confirm gate can state it plainly (refined after the first live run,
which could never reach merge on a repository without required
reviews).

Prints one decision-doc JSON object to stdout (status "proposed"). The
`facts` object carries the raw inputs the orchestrator needs for Act,
including `defaultBranch` (the base to open a PR against when none
exists yet).

Exit 1 with "ERROR: ..." on stderr when: the repo path is not a
directory (repo-invalid); the fixture file is missing or not valid JSON
(pr-state-unparseable); or gh fails for any reason other than "no pull
request found" (gh-unreachable).
"""
import json
import subprocess
import sys
from pathlib import Path

PR_FIELDS = (
    "number,state,isDraft,mergeable,mergeStateStatus,reviewDecision,"
    "statusCheckRollup,baseRefName,headRefName,title,url"
)
REPO_FIELDS = (
    "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed,deleteBranchOnMerge,"
    "defaultBranchRef"
)
OPTIONS = [
    "open-pr", "already-merged", "closed", "mark-ready", "resolve-conflicts",
    "fix-failing-checks", "wait-for-checks", "address-review",
    "request-review", "merge",
]
FAILED = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
PENDING = {"PENDING", "IN_PROGRESS", "QUEUED", "WAITING", "REQUESTED", "EXPECTED"}


def _gh_json(args, cwd):
    result = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def load_live(repo, pr_number):
    view = ["pr", "view"] + ([str(pr_number)] if pr_number else []) + ["--json", PR_FIELDS]
    code, out, err = _gh_json(view, repo)
    if code != 0:
        if "no pull requests found" in err.lower() or "could not find" in err.lower():
            pr = None
        else:
            sys.exit(f"ERROR: gh pr view failed (gh-unreachable): {err.strip()}")
    else:
        try:
            pr = json.loads(out)
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: gh pr view returned unparseable JSON (pr-state-unparseable): {e}")
    code, out, err = _gh_json(["repo", "view", "--json", REPO_FIELDS], repo)
    if code != 0:
        sys.exit(f"ERROR: gh repo view failed (gh-unreachable): {err.strip()}")
    try:
        repo_info = json.loads(out)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: gh repo view returned unparseable JSON (pr-state-unparseable): {e}")
    return pr, repo_info


def load_fixture(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load PR state file {path} (pr-state-unparseable): {e}")
    if not isinstance(data, dict) or "repo" not in data or "pr" not in data:
        sys.exit(f"ERROR: PR state file {path} must be an object with 'pr' and 'repo' keys (pr-state-unparseable)")
    return data["pr"], data["repo"]


def check_outcome(item):
    """Normalize a statusCheckRollup entry (CheckRun or StatusContext)."""
    value = item.get("conclusion") or item.get("state") or item.get("status") or ""
    return value.upper()


def merge_strategy(repo_info):
    if repo_info.get("squashMergeAllowed"):
        return "squash"
    if repo_info.get("mergeCommitAllowed"):
        return "merge"
    if repo_info.get("rebaseMergeAllowed"):
        return "rebase"
    return None


def decide(pr, repo_info):
    drivers = []
    if pr is None:
        drivers.append("no open pull request exists for the current branch")
        return "open-pr", drivers, None
    drivers.append(f"PR #{pr.get('number')} state={pr.get('state')} draft={pr.get('isDraft')}")
    state = (pr.get("state") or "").upper()
    if state == "MERGED":
        return "already-merged", drivers, None
    if state == "CLOSED":
        return "closed", drivers, None
    if pr.get("isDraft"):
        return "mark-ready", drivers, None
    drivers.append(f"mergeable={pr.get('mergeable')} mergeStateStatus={pr.get('mergeStateStatus')}")
    if (pr.get("mergeable") or "").upper() == "CONFLICTING":
        return "resolve-conflicts", drivers, None
    checks = pr.get("statusCheckRollup") or []
    outcomes = [check_outcome(c) for c in checks]
    drivers.append(f"checks={len(checks)} outcomes={sorted(set(outcomes)) or 'none reported'}")
    if any(o in FAILED for o in outcomes):
        return "fix-failing-checks", drivers, None
    if any(o in PENDING for o in outcomes):
        return "wait-for-checks", drivers, None
    review = (pr.get("reviewDecision") or "").upper()
    drivers.append(f"reviewDecision={review or 'none'}")
    if review == "CHANGES_REQUESTED":
        return "address-review", drivers, None
    if review == "REVIEW_REQUIRED":
        return "request-review", drivers, None
    if review != "APPROVED":
        drivers.append("no review required by branch protection — merging without an approving review")
    strategy = merge_strategy(repo_info)
    drivers.append(f"merge strategy={strategy} (repo settings)")
    return "merge", drivers, strategy


JUSTIFICATION = {
    "open-pr": "Nothing can be reviewed or merged until a pull request exists.",
    "already-merged": "The pull request is already merged; there is nothing to do.",
    "closed": "The pull request is closed; reopen it deliberately before continuing.",
    "mark-ready": "Draft pull requests cannot be merged; a human must mark it ready.",
    "resolve-conflicts": "GitHub reports merge conflicts; they must be resolved on the branch first.",
    "fix-failing-checks": "At least one required check failed; merging would land red.",
    "wait-for-checks": "Checks are still running; the tree has not been judged yet.",
    "address-review": "A reviewer requested changes; merging would override review.",
    "request-review": "No approving review exists; request one before merging.",
    "merge": "Checks are green (or none are required), review is approved (or none is required by branch protection — see drivers), and the branch is mergeable.",
}


def main():
    args = sys.argv[1:]
    fixture = None
    pr_number = None
    if "--pr-json-file" in args:
        i = args.index("--pr-json-file")
        if i + 1 >= len(args):
            sys.exit("ERROR: --pr-json-file requires a path")
        fixture = args[i + 1]
        del args[i:i + 2]
    if "--pr" in args:
        i = args.index("--pr")
        if i + 1 >= len(args):
            sys.exit("ERROR: --pr requires a number")
        pr_number = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: assess_pr_readiness.py <repo-path> [--pr <number>] [--pr-json-file <path>]")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")

    pr, repo_info = load_fixture(fixture) if fixture else load_live(repo, pr_number)
    chosen, drivers, strategy = decide(pr, repo_info)

    doc = {
        "status": "proposed",
        "contextAndProblemStatement": (
            "Decide the next lifecycle action for the pull request on the current "
            "branch: open it, wait, request or address review, or merge."
        ),
        "decisionDrivers": drivers,
        "consideredOptions": OPTIONS,
        "decisionOutcome": {
            "chosenOption": chosen,
            "justification": JUSTIFICATION[chosen],
        },
        "consequences": {
            "positive": ["the next action is derived from GitHub's own state, not guessed"],
            "negative": (
                ["merging is irreversible; it proceeds only after the high-risk gate"]
                if chosen == "merge" else []
            ),
        },
        "confirmation": (
            "Re-run this assessment immediately before Act; act only if the chosen "
            "option is unchanged."
        ),
        "facts": {
            "prNumber": pr.get("number") if pr else None,
            "prUrl": pr.get("url") if pr else None,
            "headRefName": pr.get("headRefName") if pr else None,
            "baseRefName": pr.get("baseRefName") if pr else None,
            "defaultBranch": (repo_info.get("defaultBranchRef") or {}).get("name"),
            "mergeStrategy": strategy,
            "deleteBranchOnMerge": bool(repo_info.get("deleteBranchOnMerge")),
        },
    }
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()
