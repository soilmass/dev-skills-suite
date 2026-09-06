#!/usr/bin/env python3
"""Scan a repository's source files for mechanical technical-debt
signals and emit them as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    scan_debt.py <repo-path> [--long-file-lines N] [--dup-window N]
                 [--ext .py,.js,...]

Three detectors, all deterministic (SDS-S-060 — this is the toil; the
prioritization that needs judgment happens in the skill's Analyze
stage, never here):

    debt/marker           a TODO, FIXME, HACK, XXX, or WORKAROUND
                          comment. FIXME/HACK/XXX -> warning; TODO/
                          WORKAROUND -> info (see
                          references/marker-taxonomy.md).
    debt/long-file        a source file longer than --long-file-lines
                          (default 500) -> warning.
    debt/duplicate-block  an identical run of --dup-window (default 8)
                          consecutive non-blank, whitespace-normalized
                          lines appearing in two or more places ->
                          warning, one finding per occurrence, all
                          sharing a `fingerprint` so a consumer can
                          group them.

Only files with the given extensions are scanned (default: common
source extensions); directories named .git, node_modules, dist, build,
vendor, target, __pycache__, and .skills-state are skipped. Files that
are not valid UTF-8 are skipped with a NOTE on stderr, never a crash.

Effect Ladder rung 1 (local-read-only): reads the working tree only;
does not consult git.

Prints one finding-list JSON document. Zero signals -> a well-formed
document with an empty `results` array (SDS-C-033). Exit 1 with
"ERROR: ..." on stderr for a path that is not a directory
(repo-invalid) or a non-integer --long-file-lines/--dup-window
(bad-argument).
"""
import hashlib
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state"}
DEFAULT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".sh", ".c", ".h", ".cpp", ".cs"}
MARKER_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|WORKAROUND)\b")
MARKER_LEVEL = {"FIXME": "warning", "HACK": "warning", "XXX": "warning", "TODO": "info", "WORKAROUND": "info"}


def iter_files(root, exts):
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file() and p.suffix in exts:
            yield p


def read_lines(p):
    try:
        return p.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        print(f"NOTE: skipping non-UTF-8 file {p}", file=sys.stderr)
        return None


def finding(rule, level, text, uri, line, extra=None):
    f = {
        "ruleId": rule,
        "level": level,
        "message": {"text": text},
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
    }
    if extra:
        f["properties"] = extra
    return f


def scan(root, long_lines, dup_window, exts):
    results = []
    windows = {}  # fingerprint -> [(uri, startLine)]
    for p in iter_files(root, exts):
        lines = read_lines(p)
        if lines is None:
            continue
        uri = str(p.relative_to(root))
        for i, line in enumerate(lines, start=1):
            m = MARKER_RE.search(line)
            if m:
                kind = m.group(1)
                results.append(finding("debt/marker", MARKER_LEVEL[kind],
                                       f"{kind} marker: {line.strip()[:120]}", uri, i, {"marker": kind}))
        if len(lines) > long_lines:
            results.append(finding("debt/long-file", "warning",
                                   f"{uri} is {len(lines)} lines (threshold {long_lines}); consider splitting by responsibility",
                                   uri, 1, {"lines": len(lines)}))
        norm = [(i, re.sub(r"\s+", " ", l).strip()) for i, l in enumerate(lines, start=1)]
        norm = [(i, l) for i, l in norm if l]
        for k in range(0, len(norm) - dup_window + 1):
            chunk = norm[k:k + dup_window]
            fp = hashlib.sha1("\n".join(l for _, l in chunk).encode()).hexdigest()[:12]
            windows.setdefault(fp, []).append((uri, chunk[0][0]))
    for fp, occ in windows.items():
        distinct = sorted(set(occ))
        if len(distinct) < 2:
            continue
        # collapse overlapping windows within the same file to their first line
        seen_files = {}
        for uri, line in distinct:
            if uri not in seen_files or line < seen_files[uri]:
                seen_files[uri] = line
        if len(seen_files) < 2 and len(distinct) < 2:
            continue
        for uri, line in sorted(seen_files.items()):
            others = [f"{u}:{l}" for u, l in sorted(seen_files.items()) if u != uri]
            results.append(finding("debt/duplicate-block", "warning",
                                   f"{dup_window}-line block duplicated with {', '.join(others) or 'another location in this file'}",
                                   uri, line, {"fingerprint": fp}))
    # dedupe duplicate-block findings that share (uri, fingerprint)
    seen = set()
    deduped = []
    for r in results:
        key = (r["ruleId"], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
               r["locations"][0]["physicalLocation"]["region"]["startLine"], r.get("properties", {}).get("fingerprint"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def main():
    args = sys.argv[1:]
    def take(flag, default):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value (bad-argument)")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    long_lines = take("--long-file-lines", "500")
    dup_window = take("--dup-window", "8")
    ext = take("--ext", None)
    if len(args) != 1:
        sys.exit("ERROR: usage: scan_debt.py <repo-path> [--long-file-lines N] [--dup-window N] [--ext .py,.js]")
    try:
        long_lines, dup_window = int(long_lines), int(dup_window)
    except ValueError:
        sys.exit(f"ERROR: --long-file-lines and --dup-window must be integers (bad-argument): {long_lines!r}, {dup_window!r}")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    exts = {e if e.startswith(".") else f".{e}" for e in ext.split(",")} if ext else DEFAULT_EXT

    results = scan(root, long_lines, dup_window, exts)
    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{"tool": {"driver": {"name": "tech-debt-inventory", "version": "0.1.0"}}, "results": results}],
    }, indent=2))


if __name__ == "__main__":
    main()
