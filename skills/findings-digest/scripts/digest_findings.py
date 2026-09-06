#!/usr/bin/env python3
"""Merge one or more finding-lists into a status-report
(kit/shapes/status-report.schema.json): totals, counts by tool, by
level, and by rule, the files with the most findings, and the errors
listed — the summary that follows "run every audit".

Usage:
    digest_findings.py <finding-list.json>... [--min-level info|warning|error] [--top N]

Effect Ladder rung 1 (SDS-S-060): files are read; nothing is run.
Each input is a finding-list (SARIF-compatible: kit/shapes/
finding-list.schema.json) as any family audit skill emits; `-` reads
one from stdin. Results are merged across inputs and runs, and a
result is counted once even when two inputs carry it (same ruleId,
location, and message text) — the case when the same audit was run
twice or two audits overlap. `--min-level` (default `info`) drops
results below a level from the counts and the listings; `--top`
(default 10) bounds each listing.

The report's sections, in order: Totals; By tool; By level; Top
rules; Files with most findings; Errors (every error at or above the
floor, up to --top per tool). `generatedFrom` names the inputs. What
to fix first, and which findings are noise, is the skill's Analyze
stage (SDS-S-061) — the digest counts, it does not rank by
importance.

Prints one status-report; inputs with no results yield a report whose
Totals section says 0 (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a file that cannot be read (input-missing), a file that is not a
finding-list (input-invalid), or a level outside the three
(level-invalid).
"""
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

LEVELS = {"note": 0, "info": 0, "warning": 1, "error": 2}


def load(path):
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"ERROR: could not read {path} (input-missing): {e}")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {path} is not JSON (input-invalid): {e}")
    if not isinstance(doc, dict) or not isinstance(doc.get("runs"), list):
        sys.exit(f"ERROR: {path} is not a finding-list: no runs array (input-invalid)")
    out = []
    for run in doc["runs"]:
        if not isinstance(run, dict) or not isinstance(run.get("results"), list):
            sys.exit(f"ERROR: {path} is not a finding-list: a run lacks a results array (input-invalid)")
        tool = ((run.get("tool") or {}).get("driver") or {}).get("name") or "unknown"
        for r in run["results"]:
            if not isinstance(r, dict) or "ruleId" not in r:
                sys.exit(f"ERROR: {path} is not a finding-list: a result lacks ruleId (input-invalid)")
            loc = ((r.get("locations") or [{}])[0].get("physicalLocation") or {})
            uri = (loc.get("artifactLocation") or {}).get("uri") or "(no location)"
            line = (loc.get("region") or {}).get("startLine")
            out.append({"tool": tool, "ruleId": r["ruleId"], "level": str(r.get("level") or "warning").lower(),
                        "text": ((r.get("message") or {}).get("text") or ""), "uri": uri, "line": line})
    return out


def main():
    args = sys.argv[1:]
    opts = {"--min-level": "info", "--top": "10"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if not args:
        sys.exit("ERROR: usage: digest_findings.py <finding-list.json>... [--min-level info|warning|error] [--top N]")
    if opts["--min-level"] not in ("info", "warning", "error"):
        sys.exit(f"ERROR: --min-level must be info, warning, or error (level-invalid): {opts['--min-level']!r}")
    try:
        top = int(opts["--top"])
        assert top > 0
    except (ValueError, AssertionError):
        sys.exit(f"ERROR: --top must be a positive integer (level-invalid): {opts['--top']!r}")
    floor = LEVELS[opts["--min-level"]]
    seen, results, inputs_total = set(), [], 0
    for path in args:
        for r in load(path):
            inputs_total += 1
            key = (r["ruleId"], r["uri"], r["line"], r["text"])
            if key in seen:
                continue
            seen.add(key)
            if LEVELS.get(r["level"], 0) >= floor:
                results.append(r)
    by_tool = Counter(r["tool"] for r in results)
    by_level = Counter(r["level"] for r in results)
    by_rule = Counter(f"{r['ruleId']} ({r['tool']})" for r in results)
    by_file = Counter(r["uri"] for r in results if r["uri"] != "(no location)")
    errors = [r for r in results if r["level"] == "error"]
    dupes = inputs_total - len(seen)

    def listing(counter, n=top):
        return "\n".join(f"- {k}: {v}" for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]) or "- none"

    per_tool = OrderedDict()
    for r in sorted(errors, key=lambda r: (r["tool"], r["uri"], r["line"] or 0)):
        per_tool.setdefault(r["tool"], []).append(r)
    err_lines = []
    for tool, rs in per_tool.items():
        for r in rs[:top]:
            where = f"{r['uri']}:{r['line']}" if r["line"] else r["uri"]
            err_lines.append(f"- [{tool}] {r['ruleId']} at {where} — {r['text'][:160]}")
        if len(rs) > top:
            err_lines.append(f"- [{tool}] … {len(rs) - top} more error(s)")
    sections = [
        {"heading": "Totals", "body": f"{len(results)} finding(s) at or above {opts['--min-level']} from {len(args)} input(s) and {len(by_tool)} tool(s); "
                                       f"{by_level.get('error', 0)} error(s), {by_level.get('warning', 0)} warning(s), {by_level.get('info', 0) + by_level.get('note', 0)} info(s); "
                                       f"{dupes} duplicate(s) merged."},
        {"heading": "By tool", "body": listing(by_tool, len(by_tool) or 1)},
        {"heading": "By level", "body": listing(by_level, 4)},
        {"heading": "Top rules", "body": listing(by_rule)},
        {"heading": "Files with most findings", "body": listing(by_file)},
        {"heading": "Errors", "body": "\n".join(err_lines) or "- none"},
    ]
    worst = "no findings" if not results else (f"{by_level.get('error', 0)} error(s) to fix first" if by_level.get("error") else "no errors; warnings and infos only")
    print(json.dumps({"summary": f"{len(results)} finding(s) across {len(by_tool)} tool(s): {worst}",
                      "generatedFrom": ", ".join(args),
                      "sections": sections}, indent=2))


if __name__ == "__main__":
    main()
