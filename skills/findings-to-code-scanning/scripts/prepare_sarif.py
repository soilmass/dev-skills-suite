#!/usr/bin/env python3
"""Prepare a GitHub Code Scanning SARIF upload payload from one or more
family finding-list inputs.

Usage:
    prepare_sarif.py <repo-path> <finding-list.json>... [--ref refs/heads/main] [--sha <40hex>]

This is the deterministic Gather-stage helper for findings-to-code-scanning
(rung 5). Every input is validated against kit/shapes/finding-list.schema.json
(the kit path is resolved from this file's own location, three parents up:
<family-root>/kit/shapes), then every run is merged into one analysis and
the SARIF-2.1.0 variant is applied — the same variant
kit/scripts/lint-skill.py's --sarif branch emits: a top-level $schema and
version "2.1.0" are added, and each result's level is narrowed from the
family's {error, warning, info, hint} to SARIF's {none, note, warning,
error} (info and hint fold to note). The merged analysis is then
gzip-compressed and base64-encoded, the form the code-scanning/sarifs
endpoint requires for its `sarif` field.

`--sha` defaults to `git rev-parse HEAD` and `--ref` to `git symbolic-ref
HEAD`, both run in <repo-path>; every eval row passes both explicitly, so
no git repository fixture is needed. The upload itself — `gh api -X POST
.../code-scanning/sarifs` — is a direct, gated tool call issued outside
this script (SDS-S-051); this script never uploads anything.

Prints one JSON object: {"commit_sha", "ref", "sarif": "<base64 gzip>",
"tool_name": "dev-skills-suite", "results": <count>}. The Act stage
strips "results" before writing the upload payload file — the endpoint
accepts only commit_sha, ref, sarif, and the optional tool_name.

Exit 1 with "ERROR: ..." on stderr for a repo-path that is not a
directory (repo-invalid), an input that fails finding-list schema
validation (findings-invalid), a --sha that is not 40 hex characters
(sha-invalid), or a --ref that does not start with refs/ (ref-invalid).
"""
import base64
import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema

SARIF_LEVEL = {"info": "note", "hint": "note"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TOOL_NAME = "dev-skills-suite"


def shapes_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "kit" / "shapes"


def load_findings(path: str, schema: dict) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: {path} is not readable JSON (findings-invalid): {e}")
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: {path} is not a finding-list (findings-invalid): {str(e).splitlines()[0]}")
    return doc


def git_value(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: git {' '.join(args)} failed in {repo}: {r.stderr.strip()}")
    return r.stdout.strip()


def take(args: list[str], flag: str) -> str | None:
    if flag not in args:
        return None
    i = args.index(flag)
    if i + 1 >= len(args):
        sys.exit(f"ERROR: {flag} requires a value")
    value = args[i + 1]
    del args[i:i + 2]
    return value


def main() -> int:
    args = sys.argv[1:]
    ref = take(args, "--ref")
    sha = take(args, "--sha")
    if len(args) < 2:
        sys.exit("ERROR: usage: prepare_sarif.py <repo-path> <finding-list.json>... [--ref refs/heads/main] [--sha <40hex>]")
    repo, inputs = Path(args[0]), args[1:]

    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")

    if sha is None:
        sha = git_value(repo, "rev-parse", "HEAD")
    if not SHA_RE.match(sha):
        sys.exit(f"ERROR: --sha must be 40 hex characters (sha-invalid): {sha!r}")

    if ref is None:
        ref = git_value(repo, "symbolic-ref", "HEAD")
    if not ref.startswith("refs/"):
        sys.exit(f"ERROR: --ref must start with refs/ (ref-invalid): {ref!r}")

    schema = json.loads((shapes_dir() / "finding-list.schema.json").read_text(encoding="utf-8"))
    merged_runs = []
    result_count = 0
    for path in inputs:
        doc = load_findings(path, schema)
        for run in doc.get("runs", []):
            for r in run.get("results", []):
                r["level"] = SARIF_LEVEL.get(r["level"], r["level"])
                result_count += 1
            merged_runs.append(run)

    sarif_doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": merged_runs,
    }
    compressed = gzip.compress(json.dumps(sarif_doc).encode("utf-8"))
    encoded = base64.b64encode(compressed).decode("ascii")

    print(json.dumps({
        "commit_sha": sha,
        "ref": ref,
        "sarif": encoded,
        "tool_name": TOOL_NAME,
        "results": result_count,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
