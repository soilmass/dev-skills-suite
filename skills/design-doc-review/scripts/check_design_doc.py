#!/usr/bin/env python3
"""Check a markdown design document for the structural gaps a reviewer
would otherwise spend the first pass on, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    check_design_doc.py <design.md> [--checklist <checklist.json>]

Effect Ladder rung 1 (SDS-S-060): the document is read, nothing is
run. The checklist (default assets/checklist.json) names the sections
a design document must have, with the heading aliases that count. The
judgment — whether the proposed design is sound, whether the
alternatives were fairly weighed — is the skill's Analyze stage
(SDS-S-061); this script reports only what is mechanically absent.

Rules emitted:

    design/missing-section     a required checklist section has no
                               heading (by any alias) -> warning
    design/empty-section       a heading followed by no body before
                               the next heading of the same or higher
                               level -> warning
    design/placeholder         TBD, TODO, FIXME, ???, XXX, or a
                               [FILL ...] marker in the body -> warning
    design/too-few-alternatives the alternatives section lists fewer
                               than two options (bullets or
                               sub-headings) -> warning; a design with
                               one alternative was not compared
    design/unowned-question    a bullet in the open-questions section
                               that names no owner (@login or a
                               "(owner: …)" tag) -> info
    design/missing-metadata    no status / author(s) / date line in
                               the first 15 lines -> info

Prints one finding-list; a complete document yields an empty
`results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a
missing or unreadable file (doc-missing), a file with no markdown
headings at all (doc-unstructured), or a checklist that does not
parse (checklist-invalid).
"""
import json
import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
PLACEHOLDER_RE = re.compile(r"\b(TBD|TODO|FIXME|XXX)\b|\?\?\?|\[FILL[^\]]*\]")
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")
OWNER_RE = re.compile(r"@[A-Za-z0-9_-]+|\(owner:\s*[^)]+\)", re.I)
META_RE = re.compile(r"^\s*(?:\*\*|_)?(status|authors?|owner|date|last updated|reviewers?)(?:\*\*|_)?\s*[:|]", re.I)


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def load_checklist(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        sections = data["sections"]
        assert isinstance(sections, list) and all("key" in s and "aliases" in s for s in sections)
    except (OSError, json.JSONDecodeError, KeyError, AssertionError, TypeError) as e:
        sys.exit(f"ERROR: checklist {path} is not a {{sections: [{{key, aliases, required}}]}} object (checklist-invalid): {e}")
    return sections


def parse(lines):
    """Return [(level, title, line, body_lines)] skipping fenced code."""
    heads, fence = [], False
    for i, raw in enumerate(lines, start=1):
        if raw.strip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        m = HEADING_RE.match(raw)
        if m:
            heads.append({"level": len(m.group(1)), "title": m.group(2).strip(), "line": i, "body": []})
        elif heads:
            heads[-1]["body"].append((i, raw))
    return heads


def section_body(heads, idx):
    """Body of heading idx including its sub-headings' bodies."""
    lvl = heads[idx]["level"]
    out = list(heads[idx]["body"])
    for h in heads[idx + 1:]:
        if h["level"] <= lvl:
            break
        out += [(h["line"], "#" * h["level"] + " " + h["title"])] + h["body"]
    return out


def main():
    args = sys.argv[1:]
    checklist = str(Path(__file__).resolve().parent.parent / "assets" / "checklist.json")
    if "--checklist" in args:
        i = args.index("--checklist")
        if i + 1 >= len(args):
            sys.exit("ERROR: --checklist requires a value")
        checklist = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: check_design_doc.py <design.md> [--checklist <checklist.json>]")
    doc = Path(args[0])
    try:
        text = doc.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        sys.exit(f"ERROR: could not read {doc} (doc-missing): {e}")
    sections = load_checklist(checklist)
    lines = text.splitlines()
    heads = parse(lines)
    if not heads:
        sys.exit(f"ERROR: {doc} has no markdown headings; nothing to review structurally (doc-unstructured)")
    uri = doc.name
    results = []

    def find(key):
        aliases = [a.lower() for a in next(s for s in sections if s["key"] == key)["aliases"]]
        for idx, h in enumerate(heads):
            t = h["title"].lower().strip(" :")
            if any(t == a or t.startswith(a) for a in aliases):
                return idx
        return None

    for s in sections:
        idx = find(s["key"])
        if idx is None and s.get("required", True):
            results.append(finding("design/missing-section", "warning",
                                   f"no {s['key']!r} section (looked for a heading named {', '.join(s['aliases'][:3])}…)",
                                   uri, 1, {"section": s["key"], "aliases": s["aliases"]}))
    for idx, h in enumerate(heads):
        if h["level"] == 1:
            continue
        body = [l for _, l in section_body(heads, idx) if l.strip()]
        if not body:
            results.append(finding("design/empty-section", "warning", f"section {h['title']!r} has no content", uri, h["line"], {"section": h["title"]}))
    fence = False
    for i, raw in enumerate(lines, start=1):
        if raw.strip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if not fence and PLACEHOLDER_RE.search(raw):
            results.append(finding("design/placeholder", "warning", f"placeholder left in the text: {raw.strip()[:80]}", uri, i, {"text": raw.strip()[:160]}))
    alt = find("alternatives")
    if alt is not None:
        body = section_body(heads, alt)
        options = sum(1 for _, l in body if BULLET_RE.match(l) or l.startswith("#"))
        if options < 2:
            results.append(finding("design/too-few-alternatives", "warning",
                                   f"the alternatives section lists {options} option(s); a design compared against fewer than two alternatives was not compared",
                                   uri, heads[alt]["line"], {"options": options}))
    oq = find("open-questions")
    if oq is not None:
        for ln, l in section_body(heads, oq):
            m = BULLET_RE.match(l)
            if m and not OWNER_RE.search(m.group(1)):
                results.append(finding("design/unowned-question", "info", f"open question has no owner: {m.group(1)[:80]}", uri, ln, {"question": m.group(1)[:160]}))
    if not any(META_RE.match(l) for l in lines[:15]):
        results.append(finding("design/missing-metadata", "info", "no status / author / date line in the first 15 lines; a reader cannot tell whether this is a draft or decided", uri, 1, {}))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["region"]["startLine"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "design-doc-review", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
