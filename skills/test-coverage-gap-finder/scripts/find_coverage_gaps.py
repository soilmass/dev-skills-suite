#!/usr/bin/env python3
"""Turn a Cobertura coverage report into a finding-list of the gaps that
name something (kit/shapes/finding-list.schema.json).

Usage:
    find_coverage_gaps.py <cobertura.xml> --repo <path> [--min-file-rate F]

Cobertura XML is the lingua franca of coverage tools (coverage.py
`coverage xml`, pytest-cov, JaCoCo, Istanbul's cobertura reporter, gcovr),
so the script consumes that rather than any tool's native store. It is
Effect Ladder rung 1 (SDS-S-060): the report and the sources are read,
nothing is run.

Per `<class filename=...>` in the report the script builds a line->hits
map. With --repo it parses the matching source file with `ast` and
intersects each function's body span (the `def` line itself is
executed at import time, so it is never evidence) with the map. Rules emitted:

    coverage/uncovered-function  a function or method none of whose
                                 tracked lines were hit -> warning;
                                 properties carry the function, its
                                 span, and the tracked line count
    coverage/low-file-rate       a file whose line-rate is below
                                 --min-file-rate (default 0.5) -> warning
    coverage/unmeasured-file     a .py file under --repo with no entry
                                 in the report at all (excluded from
                                 measurement, or never imported) -> info

Functions shaped like tests (`test_*`) and dunders are skipped. Which
uncovered function is actually risky — a public entry point versus a
`__repr__` helper — is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; a report with every function hit yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
when the report does not parse or has no <coverage> root
(report-malformed), the report path does not exist (report-missing),
--repo is not a directory (repo-invalid), or a source file does not
parse (source-unparseable).
"""
import ast
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def functions(tree, prefix=""):
    for node in tree.body if isinstance(tree, ast.Module) else tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield prefix + node.name, node.lineno, getattr(node, "end_lineno", node.lineno), node
        elif isinstance(node, ast.ClassDef):
            yield from functions(node, prefix + node.name + ".")


def main():
    args = sys.argv[1:]
    repo = None
    min_rate = 0.5
    for flag in ("--repo", "--min-file-rate"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            if flag == "--repo":
                repo = Path(args[i + 1])
            else:
                try:
                    min_rate = float(args[i + 1])
                except ValueError:
                    sys.exit("ERROR: --min-file-rate must be a number (rate-invalid)")
                if not 0 <= min_rate <= 1:
                    sys.exit("ERROR: --min-file-rate must be between 0 and 1 (rate-invalid)")
            del args[i:i + 2]
    if len(args) != 1 or repo is None:
        sys.exit("ERROR: usage: find_coverage_gaps.py <cobertura.xml> --repo <path> [--min-file-rate F]")
    report = Path(args[0])
    if not report.is_file():
        sys.exit(f"ERROR: coverage report not found (report-missing): {report}")
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    try:
        root = ET.parse(report).getroot()
    except ET.ParseError as e:
        sys.exit(f"ERROR: {report} is not well-formed XML (report-malformed): {e}")
    if root.tag != "coverage":
        sys.exit(f"ERROR: {report} root element is <{root.tag}>, not <coverage> (report-malformed)")

    results = []
    measured = set()
    for cls in root.iter("class"):
        filename = cls.get("filename")
        if not filename:
            continue
        measured.add(filename)
        hits = {}
        for ln in cls.iter("line"):
            try:
                hits[int(ln.get("number"))] = int(ln.get("hits", "0"))
            except (TypeError, ValueError):
                sys.exit(f"ERROR: {report} has a <line> without a numeric number/hits (report-malformed)")
        try:
            rate = float(cls.get("line-rate", "0"))
        except ValueError:
            sys.exit(f"ERROR: {report} has a non-numeric line-rate on {filename} (report-malformed)")
        if hits and rate < min_rate:
            results.append(finding("coverage/low-file-rate", "warning",
                                   f"{filename} line coverage is {rate:.0%}, below {min_rate:.0%} ({sum(1 for h in hits.values() if h)} of {len(hits)} tracked lines hit)",
                                   filename, 1, {"lineRate": rate, "minFileRate": min_rate, "trackedLines": len(hits),
                                                 "hitLines": sum(1 for h in hits.values() if h)}))
        src = repo / filename
        if not src.is_file():
            continue
        try:
            tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
        except SyntaxError as e:
            sys.exit(f"ERROR: {filename} does not parse (source-unparseable): {e}")
        for name, start, end, node in functions(tree):
            short = name.rsplit(".", 1)[-1]
            if short.startswith("test_") or (short.startswith("__") and short.endswith("__")):
                continue
            body_start = node.body[0].lineno  # the def line is executed at import time
            tracked = [n for n in range(body_start, end + 1) if n in hits]
            if tracked and not any(hits[n] for n in tracked):
                results.append(finding("coverage/uncovered-function", "warning",
                                       f"{filename}:{name}() has no covered lines ({len(tracked)} tracked lines, lines {start}-{end})",
                                       filename, start, {"function": name, "startLine": start, "endLine": end,
                                                         "trackedLines": len(tracked), "public": not short.startswith("_")}))
    for p in sorted(repo.rglob("*.py")):
        rel = p.relative_to(repo)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.name.startswith("test_") or "tests" in rel.parts:
            continue
        if str(rel) not in measured and rel.as_posix() not in measured:
            results.append(finding("coverage/unmeasured-file", "info",
                                   f"{rel.as_posix()} does not appear in the coverage report; it was excluded from measurement or never imported",
                                   rel.as_posix(), 1, {}))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "test-coverage-gap-finder", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
