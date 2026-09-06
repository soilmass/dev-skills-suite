#!/usr/bin/env python3
"""Compare measured page metrics against a performance budget and emit
a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    check_budget.py --budget <budget.json> --metrics <metrics.json>
                    [--baseline <metrics.json>] [--tolerance <percent>]
                    [--near <percent>]

Budget format is the Lighthouse CI budget.json (SDS-C-031, standards
first): an array of entries, each with a `path` and any of
    "timings":        [{"metric": "interactive", "budget": 3000}, ...]   (ms)
    "resourceSizes":  [{"resourceType": "script", "budget": 200}, ...]  (KB)
    "resourceCounts": [{"resourceType": "third-party", "budget": 10}]
A path of "/*" applies to every measured path that no more specific
entry covers.

Metrics format (one measured run, keyed by path):
    {"/checkout": {"timings": {"interactive": 3400, ...},
                   "resourceSizes": {"script": 240, ...},
                   "resourceCounts": {"third-party": 12}}, ...}
A Lighthouse report can be reduced to this with a small adapter; the
check itself is format-agnostic beyond these keys.

Detectors (deterministic; whether a breach matters is the skill's
Analyze stage, never this script's — SDS-S-061):
    perf/over-budget   measured > budget                       -> error
    perf/near-budget   measured within --near percent of the
                       budget (default 10) but not over        -> info
    perf/regression    with --baseline: measured worse than the
                       baseline by more than --tolerance
                       percent (default 5), even if within
                       budget                                  -> warning
    perf/no-data       a budgeted path or metric has no
                       measurement                             -> info

Prints one finding-list document. An empty budget, or a budget every
measurement satisfies with room to spare, yields a well-formed
document with an empty `results` array (SDS-C-033). Exit 1 with
"ERROR: ..." on stderr for an unreadable/malformed budget
(budget-unparseable), metrics or baseline (metrics-unparseable), or a
non-numeric --tolerance/--near (bad-argument).
"""
import json
import sys
from pathlib import Path

CATEGORIES = (("timings", "metric"), ("resourceSizes", "resourceType"), ("resourceCounts", "resourceType"))
UNITS = {"timings": "ms", "resourceSizes": "KB", "resourceCounts": ""}


def load(path, what, code):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load {what} {path} ({code}): {e}")


def finding(rule, level, text, path, props):
    return {
        "ruleId": rule,
        "level": level,
        "message": {"text": text},
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": path}}}],
        "properties": props,
    }


def budget_for(budgets, path):
    exact = [b for b in budgets if b.get("path") == path]
    if exact:
        return exact[0]
    wild = [b for b in budgets if b.get("path") in ("/*", "*", None)]
    return wild[0] if wild else None


def check(budgets, metrics, baseline, tolerance, near):
    results = []
    if not isinstance(budgets, list):
        sys.exit("ERROR: budget.json must be an array of entries (budget-unparseable)")
    paths = sorted(set(metrics) | {b["path"] for b in budgets if b.get("path") not in ("/*", "*", None)})
    for path in paths:
        b = budget_for(budgets, path)
        measured = metrics.get(path)
        if b is None:
            continue
        if measured is None:
            results.append(finding("perf/no-data", "info", f"{path}: budgeted but not measured in this run", path,
                                   {"path": path}))
            continue
        base = (baseline or {}).get(path, {})
        for cat, key in CATEGORIES:
            for item in b.get(cat, []):
                name, limit = item.get(key), item.get("budget")
                if name is None or limit is None:
                    continue
                value = (measured.get(cat) or {}).get(name)
                unit = UNITS[cat]
                props = {"path": path, "category": cat, "metric": name, "budget": limit, "measured": value}
                if value is None:
                    results.append(finding("perf/no-data", "info", f"{path} {name}: budgeted at {limit}{unit} but not measured", path, props))
                    continue
                if value > limit:
                    over = round((value - limit) / limit * 100, 1)
                    results.append(finding("perf/over-budget", "error",
                                           f"{path} {name} is {value}{unit}, over its {limit}{unit} budget by {over}%", path,
                                           dict(props, overBy=over)))
                elif limit and value >= limit * (1 - near / 100):
                    headroom = round((limit - value) / limit * 100, 1)
                    results.append(finding("perf/near-budget", "info",
                                           f"{path} {name} is {value}{unit}, within {headroom}% of its {limit}{unit} budget", path,
                                           dict(props, headroom=headroom)))
                prev = (base.get(cat) or {}).get(name)
                if prev is not None and prev > 0 and value > prev * (1 + tolerance / 100):
                    delta = round((value - prev) / prev * 100, 1)
                    results.append(finding("perf/regression", "warning",
                                           f"{path} {name} regressed {delta}% against the baseline ({prev}{unit} -> {value}{unit})", path,
                                           dict(props, baseline=prev, regressedBy=delta)))
    order = {"error": 0, "warning": 1, "info": 2}
    results.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["ruleId"]))
    return results


def main():
    args = sys.argv[1:]
    def take(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value (bad-argument)")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    budget = take("--budget")
    metrics = take("--metrics")
    baseline = take("--baseline")
    tolerance = take("--tolerance", "5")
    near = take("--near", "10")
    if args or not budget or not metrics:
        sys.exit("ERROR: usage: check_budget.py --budget <budget.json> --metrics <metrics.json> [--baseline <metrics.json>] [--tolerance <pct>] [--near <pct>]")
    try:
        tolerance, near = float(tolerance), float(near)
    except ValueError:
        sys.exit(f"ERROR: --tolerance and --near must be numbers (bad-argument): {tolerance!r}, {near!r}")

    budgets = load(budget, "budget", "budget-unparseable")
    measured = load(metrics, "metrics", "metrics-unparseable")
    base = load(baseline, "baseline metrics", "metrics-unparseable") if baseline else None
    if not isinstance(measured, dict) or (base is not None and not isinstance(base, dict)):
        sys.exit("ERROR: metrics files must be objects keyed by path (metrics-unparseable)")

    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{"tool": {"driver": {"name": "performance-budget-check", "version": "0.1.0"}},
                  "results": check(budgets, measured, base, tolerance, near)}],
    }, indent=2))


if __name__ == "__main__":
    main()
