#!/usr/bin/env python3
"""Check an RFC specification for completeness and render it.

Usage:
    render_rfc.py <rfc.json> --out-dir <dir> [--dry-run]

The input conforms to assets/rfc.schema.json, this skill's own
intermediate shape (SDS-S-080). The model composes it in the Decide
stage; this script does only what is mechanical (SDS-S-060):

  1. validates the JSON against the asset schema;
  2. refuses (rfc-incomplete) an open question whose `owner` is blank
     or anonymous ("someone", "TBD", "?"), a risk whose `mitigation`
     is blank, and any leftover placeholder (TBD, TODO, FIXME, ???,
     [FILL …]) in any text field — an RFC that ships a placeholder
     ships a question disguised as an answer;
  3. renders <out-dir>/<slug>.md with a status/authors/date line and
     the sections design-doc-review's checklist requires, in its
     order (rung 4, local-write).

`--dry-run` prints everything and writes nothing. Output:
{"path", "warnings", "sections", "rendered"?}. Warnings (never
failures): a summary over three sentences; a proposal shorter than
the motivation. Exit 1 with "ERROR: ..." on stderr for an
unreadable/malformed input (rfc-unparseable), a spec failing the
shape (rfc-invalid), an incomplete spec (rfc-incomplete), or a
missing output directory (out-dir-missing). Requires the `jsonschema`
package.
"""
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")

PLACEHOLDER_RE = re.compile(r"\b(TBD|TODO|FIXME|XXX)\b|\?\?\?|\[FILL[^\]]*\]")
ANONYMOUS = {"", "someone", "tbd", "?", "unknown", "n/a", "anyone", "team"}


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "rfc"


def walk_strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")


def render(rfc):
    L = [f"# RFC: {rfc['title']}", "",
         f"**Status:** {rfc['status']} · **Authors:** {', '.join(rfc['authors'])} · **Date:** {rfc['date']}", "",
         "## Summary", "", rfc["summary"], "",
         "## Motivation", "", rfc["motivation"], "",
         "## Goals", ""] + [f"- {g}" for g in rfc["goals"]] + ["",
         "## Non-goals", ""] + [f"- {g}" for g in rfc["nonGoals"]] + ["",
         "## Proposed design", "", rfc["proposal"], "",
         "## Alternatives considered", ""]
    for a in rfc["alternatives"]:
        L += [f"### {a['name']}", ""]
        if a.get("description"):
            L += [a["description"], ""]
        L += [f"**Why not:** {a['whyNot']}", ""]
    L += ["## Risks and mitigations", ""] + [f"- **{r['risk']}** — {r['mitigation']}" for r in rfc["risks"]] + ["",
          "## Rollout", "", rfc["rollout"]["plan"], "", f"**Rollback:** {rfc['rollout']['rollback']}", ""]
    if rfc.get("openQuestions"):
        L += ["## Open questions", ""] + [f"- {q['question']} (owner: {q['owner']}){' — blocking' if q.get('blocking') else ''}" for q in rfc["openQuestions"]] + [""]
    return "\n".join(L)


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    if dry:
        args.remove("--dry-run")
    out_dir = None
    if "--out-dir" in args:
        i = args.index("--out-dir")
        if i + 1 >= len(args):
            sys.exit("ERROR: --out-dir requires a value")
        out_dir = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1 or out_dir is None:
        sys.exit("ERROR: usage: render_rfc.py <rfc.json> --out-dir <dir> [--dry-run]")
    try:
        rfc = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: {args[0]}: {e} (rfc-unparseable)")
    schema = json.loads((Path(__file__).resolve().parent.parent / "assets" / "rfc.schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.validate(rfc, schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: specification fails assets/rfc.schema.json at {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message} (rfc-invalid)")
    for i, q in enumerate(rfc.get("openQuestions") or [], start=1):
        if q.get("owner", "").strip().lower() in ANONYMOUS:
            sys.exit(f"ERROR: open question {i} ({q['question'][:40]!r}) has no owner; name who will answer it (rfc-incomplete)")
    for i, r in enumerate(rfc["risks"], start=1):
        if not r["mitigation"].strip():
            sys.exit(f"ERROR: risk {i} ({r['risk'][:40]!r}) has no mitigation; write one or the word 'accepted' with the reason (rfc-incomplete)")
    for path, text in walk_strings(rfc):
        if PLACEHOLDER_RE.search(text):
            sys.exit(f"ERROR: placeholder left in {path}: {text.strip()[:60]!r} (rfc-incomplete)")
    if not out_dir.is_dir():
        sys.exit(f"ERROR: output directory does not exist (out-dir-missing): {out_dir}")
    warnings = []
    if len(re.findall(r"[.!?](\s|$)", rfc["summary"])) > 3:
        warnings.append("the summary runs past three sentences; a reader decides whether to read on from the summary alone")
    if len(rfc["proposal"]) < len(rfc["motivation"]):
        warnings.append("the proposal is shorter than the motivation; check that it says what will actually be built")
    rendered = render(rfc)
    path = out_dir / f"{slugify(rfc['title'])}.md"
    result = {"path": str(path), "warnings": warnings, "sections": [l[3:] for l in rendered.splitlines() if l.startswith("## ")]}
    if dry:
        result["rendered"] = rendered
    else:
        path.write_text(rendered, encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
