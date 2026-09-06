#!/usr/bin/env python3
"""Audit GitHub Actions workflow files for the mistakes that cost the
most in practice, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    audit_workflows.py <repo-path>

Reads every `.github/workflows/*.yml|*.yaml` (Effect Ladder rung 1,
SDS-S-060: files only, no API, nothing is run). Requires PyYAML
(`compatibility` in SKILL.md names it). Rules emitted:

    ci/unpinned-action             `uses:` pinned to a branch (`@main`,
                                   `@master`) -> warning; pinned to a
                                   tag rather than a commit SHA -> info
                                   (a tag can be moved; a SHA cannot)
    ci/broad-permissions           `permissions: write-all`, or a
                                   top-level/job `contents: write`
                                   without a job that needs it (any job
                                   that pushes, releases, or tags) ->
                                   warning
    ci/pull-request-target-checkout a `pull_request_target` workflow
                                   that checks out the pull request's
                                   head ref -> warning (the classic
                                   secrets-exposure hole)
    ci/secret-in-run-echo          a `run:` step that echoes or prints
                                   `${{ secrets.* }}` -> warning
    ci/no-timeout                  a job without `timeout-minutes` ->
                                   info (the default is six hours)
    ci/no-concurrency              a workflow triggered by
                                   `pull_request` or `push` without a
                                   `concurrency` group -> info (stale
                                   runs pile up)

Whether a finding matters here — a branch pin on an action the
repository owns, a write permission a release job really needs — is
the skill's Analyze stage (SDS-S-061).

Prints one finding-list; a repository with no workflows, or clean
ones, yields an empty `results` array (SDS-C-033). Exit 1 with
"ERROR: ..." on stderr for a path that is not a directory
(repo-invalid) or a workflow that is not valid YAML or not a mapping
(workflow-malformed).
"""
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("ERROR: PyYAML is required (pip install pyyaml)")

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCHES = {"main", "master", "develop", "trunk", "HEAD"}
SECRET_ECHO_RE = re.compile(r"\b(echo|print|printf|cat|Write-Host)\b[^\n]*\$\{\{\s*secrets\.")
HEAD_REF_RE = re.compile(r"github\.event\.pull_request\.head\.(sha|ref)|refs/pull/")


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def line_of(text, needle, start=1):
    """1-based line of the first occurrence of `needle` at or after line `start`."""
    lines = text.splitlines()
    for i in range(start - 1, len(lines)):
        if needle in lines[i]:
            return i + 1
    return 1


def audit(doc, text, rel):
    results = []
    # PyYAML parses the bare key `on` as boolean True
    on = doc.get("on", doc.get(True, {}))
    triggers = set(on.keys()) if isinstance(on, dict) else {on} if isinstance(on, str) else set(on or [])
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return results
    if ({"pull_request", "push"} & triggers) and "concurrency" not in doc:
        results.append(finding("ci/no-concurrency", "info",
                               f"{rel} runs on {', '.join(sorted({'pull_request', 'push'} & triggers))} without a concurrency group; superseded runs keep running",
                               rel, 1, {"triggers": sorted(triggers)}))
    top_perms = doc.get("permissions")
    if top_perms == "write-all" or (isinstance(top_perms, dict) and top_perms.get("contents") == "write"):
        results.append(finding("ci/broad-permissions", "warning",
                               f"{rel} grants {'write-all' if top_perms == 'write-all' else 'contents: write'} to every job",
                               rel, line_of(text, "permissions:"), {"scope": "workflow", "permissions": top_perms}))
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_line = line_of(text, f"{job_name}:")
        if "timeout-minutes" not in job and "uses" not in job:
            results.append(finding("ci/no-timeout", "info",
                                   f"job {job_name!r} has no timeout-minutes; a hung step runs for six hours",
                                   rel, job_line, {"job": job_name}))
        perms = job.get("permissions")
        if perms == "write-all":
            results.append(finding("ci/broad-permissions", "warning",
                                   f"job {job_name!r} requests write-all",
                                   rel, line_of(text, "permissions:", job_line), {"scope": "job", "job": job_name, "permissions": perms}))
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if isinstance(uses, str) and "@" in uses and not uses.startswith("./") and not uses.startswith("docker://"):
                action, ref = uses.rsplit("@", 1)
                s_line = line_of(text, uses)
                if ref in BRANCHES:
                    results.append(finding("ci/unpinned-action", "warning",
                                           f"{action} is pinned to branch {ref!r}; every run picks up whatever is there now",
                                           rel, s_line, {"job": job_name, "action": action, "ref": ref, "pin": "branch"}))
                elif not SHA_RE.match(ref):
                    results.append(finding("ci/unpinned-action", "info",
                                           f"{action} is pinned to tag {ref!r}, which can be moved; a commit SHA cannot",
                                           rel, s_line, {"job": job_name, "action": action, "ref": ref, "pin": "tag"}))
                if "pull_request_target" in triggers and action.endswith("/checkout"):
                    with_ = step.get("with") or {}
                    ref_expr = str(with_.get("ref", ""))
                    if HEAD_REF_RE.search(ref_expr):
                        results.append(finding("ci/pull-request-target-checkout", "warning",
                                               f"job {job_name!r} runs on pull_request_target and checks out the pull request head ({ref_expr}); untrusted code runs with this repository's secrets",
                                               rel, s_line, {"job": job_name, "ref": ref_expr}))
            run = step.get("run")
            if isinstance(run, str) and SECRET_ECHO_RE.search(run):
                results.append(finding("ci/secret-in-run-echo", "warning",
                                       f"job {job_name!r} prints a secret in a run step; it lands in the log",
                                       rel, line_of(text, "secrets.", job_line), {"job": job_name}))
    return results


def main():
    args = sys.argv[1:]
    if len(args) != 1:
        sys.exit("ERROR: usage: audit_workflows.py <repo-path>")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    wf_dir = root / ".github" / "workflows"
    results = []
    for p in sorted(wf_dir.glob("*.y*ml")) if wf_dir.is_dir() else []:
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8")
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as e:
            sys.exit(f"ERROR: {rel} is not valid YAML (workflow-malformed): {e}")
        if not isinstance(doc, dict):
            sys.exit(f"ERROR: {rel} is not a workflow mapping (workflow-malformed)")
        results += audit(doc, text, rel)
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "ci-pipeline-audit", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
