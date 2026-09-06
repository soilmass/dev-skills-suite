#!/usr/bin/env python3
"""Assess a branch against its base and upstream and recommend exactly
one sync action, as a decision-doc (kit/shapes/decision-doc.schema.json).

Usage:
    assess_sync_state.py <repo-path> [--branch <name>] [--base <ref>]
    assess_sync_state.py <repo-path> --facts-file <path>

Reads only local git state (Effect Ladder rung 2, domain-read-only):
it never fetches, pulls, rebases, merges, or pushes. Run `git fetch`
first; the remote-tracking refs it compares against must already be
present (a missing one is a `refs-missing` failure, not a silent
"up to date").

Facts gathered (all from plain git plumbing):
    branch, upstream (the @{u} ref or null), base (default: the
    remote's HEAD branch, else origin/main), aheadUpstream/
    behindUpstream, aheadBase/behindBase, conflictsPredicted (old-style
    `git merge-tree <merge-base> <base> <branch>`, compatible with git
    2.34: any conflict marker or "changed in both" hunk counts),
    dirtyWorkTree (`git status --porcelain` non-empty).

`--facts-file` is the injectable-fixture flag (SDS-S-065): it
substitutes a JSON object of those facts for the git calls, so every
row of the rule table can be exercised offline — including states that
are awkward to construct in a fixture repository (a branch that
diverged from its own upstream, a dirty tree).

Rule table (first match wins):
    dirtyWorkTree                              -> stash-or-commit-first
    base ref missing locally                   -> fetch-first
    upstream and behindUpstream>0, aheadUpstream>0 -> reconcile-upstream
    upstream and behindUpstream>0, aheadUpstream==0-> pull-fast-forward
    behindBase>0 and conflictsPredicted        -> resolve-conflicts
    behindBase>0 and branch fully pushed       -> merge-base
      (upstream exists, aheadUpstream==0: rebasing would rewrite
       history others may already have)
    behindBase>0 otherwise                     -> rebase-onto-base
    no upstream and aheadBase>0                -> publish-branch
    upstream and aheadUpstream>0               -> push
    otherwise                                  -> up-to-date

"Fully pushed" is a heuristic for "shared": the script cannot know who
else has the branch. The skill's Analyze stage lets the user override
merge-base vs rebase-onto-base when they know the branch is private or
shared; the script only records the heuristic in decisionDrivers.

Prints one decision-doc JSON object (status "proposed") with a `facts`
object. Exit 1 with "ERROR: ..." on stderr for: not a git repository
root (repo-invalid); the branch does not exist (branch-missing); the
base ref does not exist locally (refs-missing); an unreadable or
malformed facts file (facts-unparseable).
"""
import json
import subprocess
import sys
from pathlib import Path

OPTIONS = [
    "stash-or-commit-first", "fetch-first", "reconcile-upstream",
    "pull-fast-forward", "resolve-conflicts", "merge-base",
    "rebase-onto-base", "publish-branch", "push", "up-to-date",
]
JUSTIFICATION = {
    "stash-or-commit-first": "The working tree has uncommitted changes; no sync operation is safe until they are stashed or committed.",
    "fetch-first": "The base's remote-tracking ref is not present locally; nothing can be compared until `git fetch` has run.",
    "reconcile-upstream": "The branch and its own upstream have both moved; reconcile them (`git pull --rebase` for a private branch, `git pull` otherwise) before touching the base.",
    "pull-fast-forward": "The upstream is ahead and the branch has no local commits; a fast-forward pull is loss-free.",
    "resolve-conflicts": "The branch is behind its base and a rebase or merge is predicted to conflict; resolve deliberately rather than as a side effect.",
    "merge-base": "The branch is behind its base and already fully pushed; merging the base in avoids rewriting history others may have.",
    "rebase-onto-base": "The branch is behind its base and has unpublished commits only; rebasing keeps history linear without rewriting anything shared.",
    "publish-branch": "The branch has commits and no upstream; publish it with `git push -u`.",
    "push": "The branch is up to date with its base and ahead of its upstream; push the local commits.",
    "up-to-date": "The branch is current with both its base and its upstream; nothing to do.",
}


def git(repo, *args, check=True):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout.strip()


def counts(repo, left, right):
    out = git(repo, "rev-list", "--left-right", "--count", f"{left}...{right}")
    a, b = out.split()
    return int(a), int(b)


def ref_exists(repo, ref):
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=repo,
                          capture_output=True).returncode == 0


def default_base(repo):
    head = subprocess.run(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
                          cwd=repo, capture_output=True, text=True)
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip().replace("refs/remotes/", "", 1)
    return "origin/main"


def predict_conflicts(repo, base, branch):
    try:
        mb = git(repo, "merge-base", base, branch)
    except RuntimeError:
        return False
    out = subprocess.run(["git", "merge-tree", mb, base, branch], cwd=repo,
                         capture_output=True, text=True).stdout
    return ("<<<<<<<" in out) or ("changed in both" in out)


def gather(repo, branch, base):
    try:
        top = git(repo, "rev-parse", "--show-toplevel")
    except RuntimeError as e:
        sys.exit(f"ERROR: not a git repository (repo-invalid): {repo}: {e}")
    if Path(top).resolve() != repo.resolve():
        sys.exit(f"ERROR: not a git repository root (repo-invalid): {repo} (root is {top})")
    branch = branch or git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if not ref_exists(repo, branch):
        sys.exit(f"ERROR: branch does not exist (branch-missing): {branch}")
    base = base or default_base(repo)
    facts = {"branch": branch, "base": base, "baseRefPresent": ref_exists(repo, base)}
    up = subprocess.run(["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
                        cwd=repo, capture_output=True, text=True)
    facts["upstream"] = up.stdout.strip() if up.returncode == 0 else None
    if facts["upstream"]:
        facts["aheadUpstream"], facts["behindUpstream"] = counts(repo, branch, facts["upstream"])
    else:
        facts["aheadUpstream"] = facts["behindUpstream"] = None
    if facts["baseRefPresent"]:
        facts["aheadBase"], facts["behindBase"] = counts(repo, branch, base)
        facts["conflictsPredicted"] = facts["behindBase"] > 0 and predict_conflicts(repo, base, branch)
    else:
        facts["aheadBase"] = facts["behindBase"] = None
        facts["conflictsPredicted"] = None
    facts["dirtyWorkTree"] = bool(git(repo, "status", "--porcelain"))
    return facts


def load_facts(path):
    try:
        facts = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load facts file {path} (facts-unparseable): {e}")
    required = {"branch", "base", "baseRefPresent", "upstream", "aheadUpstream",
                "behindUpstream", "aheadBase", "behindBase", "conflictsPredicted", "dirtyWorkTree"}
    if not isinstance(facts, dict) or not required <= set(facts):
        sys.exit(f"ERROR: facts file {path} lacks required keys (facts-unparseable): {sorted(required - set(facts or {}))}")
    return facts


def decide(f):
    d = [f"branch={f['branch']} base={f['base']} upstream={f['upstream'] or 'none'}"]
    if f["dirtyWorkTree"]:
        d.append("working tree is dirty")
        return "stash-or-commit-first", d
    if not f["baseRefPresent"]:
        d.append(f"base ref {f['base']} is not present locally")
        return "fetch-first", d
    d.append(f"aheadBase={f['aheadBase']} behindBase={f['behindBase']} conflictsPredicted={f['conflictsPredicted']}")
    if f["upstream"]:
        d.append(f"aheadUpstream={f['aheadUpstream']} behindUpstream={f['behindUpstream']}")
        if f["behindUpstream"] > 0 and f["aheadUpstream"] > 0:
            return "reconcile-upstream", d
        if f["behindUpstream"] > 0:
            return "pull-fast-forward", d
    if f["behindBase"] > 0:
        if f["conflictsPredicted"]:
            return "resolve-conflicts", d
        fully_pushed = bool(f["upstream"]) and f["aheadUpstream"] == 0
        d.append("branch is fully pushed — treated as shared (heuristic)" if fully_pushed
                 else "branch has unpublished commits or no upstream — treated as private (heuristic)")
        return ("merge-base" if fully_pushed else "rebase-onto-base"), d
    if not f["upstream"] and f["aheadBase"] > 0:
        return "publish-branch", d
    if f["upstream"] and f["aheadUpstream"] > 0:
        return "push", d
    return "up-to-date", d


def main():
    args = sys.argv[1:]
    def take(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None
    facts_file = take("--facts-file")
    branch = take("--branch")
    base = take("--base")
    if len(args) != 1:
        sys.exit("ERROR: usage: assess_sync_state.py <repo-path> [--branch <name>] [--base <ref>] [--facts-file <path>]")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")

    facts = load_facts(facts_file) if facts_file else gather(repo, branch, base)
    if not facts_file and not facts["baseRefPresent"] and base:
        sys.exit(f"ERROR: base ref does not exist locally (refs-missing): {base} — run git fetch")
    chosen, drivers = decide(facts)
    doc = {
        "status": "proposed",
        "contextAndProblemStatement": (
            f"Decide how to bring branch {facts['branch']} into sync with its base "
            f"{facts['base']} and upstream {facts['upstream'] or '(none)'} without losing or rewriting shared work."
        ),
        "decisionDrivers": drivers,
        "consideredOptions": OPTIONS,
        "decisionOutcome": {"chosenOption": chosen, "justification": JUSTIFICATION[chosen]},
        "consequences": {
            "positive": ["the action is derived from measured git state, not guessed"],
            "negative": (["rewrites local history; safe only while the branch is private"]
                         if chosen == "rebase-onto-base" else []),
        },
        "confirmation": "Re-run this assessment after fetching and again after performing the chosen action; expect up-to-date or push.",
        "facts": facts,
    }
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()
