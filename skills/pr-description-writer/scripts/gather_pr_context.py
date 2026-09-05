#!/usr/bin/env python3
"""Gather the diff, commit history, and (if one exists) the current PR
body for the current branch, normalized for the Analyze/Decide stage.

Usage:
    gather_pr_context.py <repo-path> --base <base-branch>
                          [--current-body-file <path>]

`--current-body-file` lets a caller (or an eval) inject the "current
PR body" instead of shelling out to `gh pr view` — this is the same
testability goal as dependency-audit's frozen-fixture pattern (the
injectable-fixture flag, SDS-S-065), applied differently: instead of
freezing the *output* of a downstream step, this script accepts a
substitute for its own live external call, so the exact same code
path is exercised in an eval as in real use.

Without `--current-body-file`, this script tries `gh pr view --json
body` for the current branch. Finding no open PR is NOT an error —
drafting a description for a PR that doesn't exist yet is a normal,
common case — currentBody is simply null in that case.

Prints a JSON object to stdout:
    {"base": str, "head": str, "files": [...], "commits": [...],
     "currentBody": str|null}

Exit code 1 with "ERROR: ..." on stderr means the repo path is invalid,
not a git repository, or the base ref doesn't exist — a genuine
precondition failure, not "no PR yet."
"""
import json
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd, check=True):
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(cmd)}")
    return result.stdout


def main():
    args = sys.argv[1:]
    if len(args) < 3 or args[1] != "--base":
        sys.exit("ERROR: usage: gather_pr_context.py <repo-path> --base <base-branch> [--current-body-file <path>]")
    repo = Path(args[0])
    base = args[2]
    current_body_file = None
    if "--current-body-file" in args:
        current_body_file = args[args.index("--current-body-file") + 1]

    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory: {repo}")
    try:
        toplevel = run(["git", "rev-parse", "--show-toplevel"], cwd=repo).strip()
    except RuntimeError as e:
        sys.exit(f"ERROR: not a git repository ({repo}): {e}")
    # <repo-path> must be the repository root itself. A plain directory
    # that merely sits inside some enclosing repository is not a
    # repository — treating it as one would diff the enclosing repo.
    if Path(toplevel).resolve() != repo.resolve():
        sys.exit(
            f"ERROR: not a git repository root ({repo}): it is a plain "
            f"directory inside the repository at {toplevel}"
        )

    try:
        head = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
    except RuntimeError as e:
        sys.exit(f"ERROR: could not resolve HEAD: {e}")

    try:
        run(["git", "rev-parse", "--verify", base], cwd=repo)
    except RuntimeError as e:
        sys.exit(f"ERROR: base ref {base!r} does not exist: {e}")

    try:
        stat_output = run(["git", "diff", "--stat", f"{base}...HEAD"], cwd=repo)
    except RuntimeError as e:
        sys.exit(f"ERROR: could not diff {base}...HEAD: {e}")

    files = []
    for line in stat_output.splitlines():
        if "|" in line:
            name, rest = line.split("|", 1)
            files.append(name.strip())

    log_output = run(
        ["git", "log", f"{base}..HEAD", "--format=%H%x09%s"], cwd=repo, check=False
    )
    commits = []
    for line in log_output.splitlines():
        if "\t" in line:
            sha, subject = line.split("\t", 1)
            commits.append({"sha": sha, "subject": subject})

    if current_body_file:
        current_body = Path(current_body_file).read_text()
    else:
        gh_result = subprocess.run(
            ["gh", "pr", "view", "--json", "body"],
            cwd=repo, capture_output=True, text=True,
        )
        if gh_result.returncode == 0:
            current_body = json.loads(gh_result.stdout).get("body")
        else:
            # No open PR for this branch (or gh unavailable) is a normal
            # case, not a fatal error — see module docstring.
            current_body = None

    print(json.dumps({
        "base": base,
        "head": head,
        "files": files,
        "commits": commits,
        "currentBody": current_body,
    }, indent=2))


if __name__ == "__main__":
    main()
