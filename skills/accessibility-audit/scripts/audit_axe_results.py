#!/usr/bin/env python3
"""Turn axe-core results into a finding-list (kit/shapes/finding-list.schema.json),
one finding per violated rule per page, with the WCAG criteria and the
affected elements carried through.

Usage:
    audit_axe_results.py <results.json | results-dir> [--min-impact minor|moderate|serious|critical]

Input: the JSON axe-core produces (`axe.run()` in the browser, the
@axe-core/cli `--save`, Playwright's @axe-core/playwright, or
Lighthouse's accessibility audits exported through axe): an object —
or an array of them, one per page — with `url`, `violations`,
`incomplete`, `passes`, and `inapplicable`, each violation carrying
`id`, `impact`, `description`, `help`, `helpUrl`, `tags` (wcag2a,
wcag21aa, best-practice, …), and `nodes` with `target` selectors and
`failureSummary`. A directory is read as one file per page.
Effect Ladder rung 1 (SDS-S-060): files only; no page is loaded.

Rules emitted:

    a11y/<axe-rule-id>    one per violated rule per page; level by
                          impact — critical and serious -> error,
                          moderate -> warning, minor -> info;
                          properties carry the WCAG criteria parsed
                          from the tags (e.g. 1.1.1, 4.1.2), the
                          conformance level (A / AA / AAA / best
                          practice), the node count, and up to five
                          selectors with their failure summaries
    a11y/needs-review     one per rule in `incomplete` per page -> info;
                          axe could not decide (contrast on a gradient,
                          an alt that may be decorative) and a human
                          must

`tool.properties` carries the pages, the violation and node totals,
counts by impact, and by WCAG level — the numbers a conformance
statement needs. Deciding which findings block a release, and what
the fix is in this codebase's components, is the skill's Analyze
stage (SDS-S-061).

Prints one finding-list; results with no violations and nothing
incomplete yield an empty `results` array (SDS-C-033). Exit 1 with
"ERROR: ..." on stderr for a path that cannot be read or parsed
(results-unparseable), a file that is not axe results (no
`violations` array) (results-invalid), or an unknown --min-impact
(impact-invalid).
"""
import json
import re
import sys
from pathlib import Path

IMPACTS = ["minor", "moderate", "serious", "critical"]
LEVEL = {"critical": "error", "serious": "error", "moderate": "warning", "minor": "info"}
WCAG_TAG_RE = re.compile(r"^wcag(\d)(\d)(\d{1,2})$")
LEVEL_TAG_RE = re.compile(r"^wcag2(1|2)?(a{1,3})$")


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}], "properties": props}


def load(path):
    p = Path(path)
    docs = []
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    if not files:
        sys.exit(f"ERROR: {path} contains no .json results (results-invalid)")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"ERROR: could not read {f} (results-unparseable): {e}")
        items = data if isinstance(data, list) else [data]
        for d in items:
            if not isinstance(d, dict) or not isinstance(d.get("violations"), list):
                sys.exit(f"ERROR: {f} is not axe-core results (no violations array) (results-invalid)")
            d.setdefault("url", f.name)
            docs.append(d)
    return docs


def criteria(tags):
    crit, level = [], None
    for t in tags or []:
        m = WCAG_TAG_RE.match(t)
        if m:
            crit.append(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
        m2 = LEVEL_TAG_RE.match(t)
        if m2:
            level = m2.group(2).upper()
    if level is None and any(t == "best-practice" for t in tags or []):
        level = "best practice"
    return sorted(set(crit)), level


def main():
    args = sys.argv[1:]
    min_impact = "minor"
    if "--min-impact" in args:
        i = args.index("--min-impact")
        if i + 1 >= len(args):
            sys.exit("ERROR: --min-impact requires a value")
        min_impact = args[i + 1]
        del args[i:i + 2]
    if min_impact not in IMPACTS:
        sys.exit(f"ERROR: --min-impact must be one of {', '.join(IMPACTS)} (impact-invalid)")
    if len(args) != 1:
        sys.exit("ERROR: usage: audit_axe_results.py <results.json | dir> [--min-impact minor|moderate|serious|critical]")
    docs = load(args[0])
    threshold = IMPACTS.index(min_impact)
    out, by_impact, by_level, nodes_total, violations_total = [], {k: 0 for k in IMPACTS}, {}, 0, 0
    for d in docs:
        url = d.get("url") or "page"
        for v in d["violations"]:
            impact = v.get("impact") or "minor"
            crit, lvl = criteria(v.get("tags"))
            nodes = v.get("nodes") or []
            violations_total += 1
            nodes_total += len(nodes)
            by_impact[impact] = by_impact.get(impact, 0) + 1
            by_level[lvl or "unknown"] = by_level.get(lvl or "unknown", 0) + 1
            if IMPACTS.index(impact) < threshold:
                continue
            out.append(finding(f"a11y/{v.get('id', 'unknown')}", LEVEL.get(impact, "info"),
                               f"{v.get('help') or v.get('description') or v.get('id')} — {len(nodes)} element(s) on {url}" + (f"; WCAG {', '.join(crit)} ({lvl})" if crit else (f" ({lvl})" if lvl else "")),
                               url, {"impact": impact, "wcag": crit, "level": lvl, "nodes": len(nodes), "helpUrl": v.get("helpUrl"),
                                     "elements": [{"target": " ".join(n.get("target") or []), "summary": (n.get("failureSummary") or "")[:200]} for n in nodes[:5]]}))
        for inc in d.get("incomplete") or []:
            crit, lvl = criteria(inc.get("tags"))
            out.append(finding("a11y/needs-review", "info",
                               f"{inc.get('help') or inc.get('id')}: axe could not decide for {len(inc.get('nodes') or [])} element(s) on {url}; a human must",
                               url, {"rule": inc.get("id"), "wcag": crit, "level": lvl, "nodes": len(inc.get("nodes") or []), "helpUrl": inc.get("helpUrl")}))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order[r["level"]], -IMPACTS.index(r["properties"].get("impact", "minor")), r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "accessibility-audit", "version": "0.1.0"},
                                         "properties": {"pages": [d.get("url") for d in docs], "violations": violations_total, "affectedElements": nodes_total,
                                                        "byImpact": by_impact, "byWcagLevel": by_level, "minImpact": min_impact,
                                                        "axeVersion": next((d.get("testEngine", {}).get("version") for d in docs if d.get("testEngine")), None)}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
