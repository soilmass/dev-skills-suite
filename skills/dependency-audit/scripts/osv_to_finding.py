#!/usr/bin/env python3
"""Adapter: OSV match records -> kit/shapes/finding-list.schema.json.

Per SDS-C-062 (Adapter pattern): this script's only job is
format translation with zero judgment. When OSV's schema or the
finding-list shape changes, this is the one file that should need
updating — the skill's Analyze/Decide reasoning never touches OSV's
raw format directly.

Usage:
    osv_to_finding.py <matches.json>
    osv_batch_query.py deps.json | osv_to_finding.py -

Prints a document conforming to finding-list.schema.json. Zero matches
in -> a valid, well-formed finding-list with an empty `results` array
out (SDS-C-033), never null or an omitted field.
"""
import json
import sys

# OSV's database_specific.severity is a coarse GitHub Security Advisory
# label (verified against the live API response shape on 2026-09-05).
# Missing/unrecognized severity maps to "warning", not "info" — an
# unknown severity must never be silently treated as low-priority.
SEVERITY_TO_LEVEL = {
    "CRITICAL": "error",
    "HIGH": "error",
    "MODERATE": "warning",
    "LOW": "info",
}


def to_finding(dependency, vuln):
    severity = vuln.get("database_specific", {}).get("severity")
    level = SEVERITY_TO_LEVEL.get(severity, "warning")

    aliases = vuln.get("aliases", [])
    alias_note = f" (aka {', '.join(aliases)})" if aliases else ""
    summary = vuln.get("summary") or "No summary provided by OSV record."
    text = (
        f"{dependency['name']}@{dependency['version']} "
        f"({dependency['ecosystem']}) is affected by {vuln['id']}"
        f"{alias_note}: {summary}"
    )

    finding = {
        "ruleId": vuln["id"],
        "level": level,
        "message": {"text": text},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": dependency.get("source", "")}
                }
            }
        ],
    }
    if not dependency.get("resolved", True):
        finding["message"]["text"] += (
            " [NOTE: version is an unresolved range from the manifest, "
            "not a lockfile-pinned version — treat as best-effort.]"
        )
    return finding


def main():
    if len(sys.argv) != 2:
        sys.exit("ERROR: usage: osv_to_finding.py <matches.json|->")
    raw = sys.stdin.read() if sys.argv[1] == "-" else open(sys.argv[1]).read()
    try:
        matches = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: input is not valid JSON: {e}")

    document = {
        "version": "sds-finding-list-1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "dependency-audit", "version": "0.1.0"}},
                "results": [to_finding(m["dependency"], m["vuln"]) for m in matches],
            }
        ],
    }
    print(json.dumps(document, indent=2))


if __name__ == "__main__":
    main()
