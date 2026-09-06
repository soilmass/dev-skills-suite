#!/usr/bin/env python3
"""Compare two versions of a JSON Schema and report the changes that make
instances valid under the old version invalid under the new one, as a
finding-list (kit/shapes/finding-list.schema.json).

Usage:
    diff_json_schema.py <old.(json|yaml)> <new.(json|yaml)>

Effect Ladder rung 1 (SDS-S-060): two files are read, nothing is
called. YAML needs PyYAML; JSON needs nothing. Local `$ref`s
(`#/$defs/...`, `#/definitions/...`) are resolved within each
document.

The question is the one a schema registry asks (backward
compatibility, in Confluent's terms): can data written under the old
schema still be read — validated — under the new one? Every change is
classified by whether it can reject a previously valid instance:

    schema/required-added        a property became required, or a new
                                 required property appeared -> error
                                 (old instances lack it)
    schema/property-removed      a property disappeared while
                                 additionalProperties is false ->
                                 error (old instances carrying it are
                                 rejected); with additional properties
                                 allowed -> warning (readers expecting
                                 it get nothing)
    schema/type-narrowed         a type set shrank (number -> integer,
                                 [string, null] -> string) -> error
    schema/type-widened          a type set grew -> info
    schema/enum-value-removed    an enum lost a value -> error
    schema/enum-value-added      an enum gained a value -> warning
                                 (readers with exhaustive handling)
    schema/constraint-tightened  minimum/exclusiveMinimum raised,
                                 maximum/exclusiveMaximum lowered,
                                 minLength/minItems/minProperties
                                 raised, maxLength/maxItems/
                                 maxProperties lowered, pattern
                                 changed, format added or changed,
                                 uniqueItems/const introduced -> error
    schema/constraint-loosened   the opposite direction -> info
    schema/additional-properties-closed additionalProperties went from
                                 allowed to false -> error
    schema/required-removed      a property is no longer required -> info

`tool.properties.backwardCompatible` is true when no error was
reported. Whether a break is acceptable — an unreleased schema, data
that never used the removed property — is the skill's Analyze stage
(SDS-S-061).

Prints one finding-list; identical schemas yield an empty `results`
array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr when a file
cannot be read or parsed (schema-unparseable) or is not a JSON Schema
object (schema-invalid).
"""
import json
import sys
from pathlib import Path

RAISE_TIGHTENS = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
LOWER_TIGHTENS = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}],
            "properties": props}


def load(path):
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError:
                sys.exit("ERROR: PyYAML is required for YAML input (pip install pyyaml)")
            doc = yaml.safe_load(text)
        else:
            doc = json.loads(text)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: could not read {path} (schema-unparseable): {e}")
    if not isinstance(doc, dict) or not any(k in doc for k in ("type", "properties", "$schema", "oneOf", "anyOf", "allOf", "$ref", "enum")):
        sys.exit(f"ERROR: {path} is not a JSON Schema object (schema-invalid)")
    return doc


def resolve(doc, schema, depth=0):
    if not isinstance(schema, dict) or depth > 20:
        return schema
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        node = doc
        for part in ref[2:].split("/"):
            node = node.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(node, dict) else {}
        return resolve(doc, node, depth + 1)
    return schema


def types(s):
    t = s.get("type")
    if t is None:
        return None
    return set(t) if isinstance(t, list) else {t}


def compare(od, nd, o, n, ptr, uri, out, seen):
    if ptr in seen:
        return
    seen.add(ptr)
    o, n = resolve(od, o), resolve(nd, n)
    if not isinstance(o, dict) or not isinstance(n, dict):
        return
    ot, nt = types(o), types(n)
    if ot and nt and ot != nt:
        if nt < ot or (ot == {"number"} and nt == {"integer"}):
            out.append(finding("schema/type-narrowed", "error", f"{ptr}: type narrowed from {sorted(ot)} to {sorted(nt)}", uri, {"pointer": ptr, "from": sorted(ot), "to": sorted(nt)}))
        elif ot < nt or (ot == {"integer"} and nt == {"number"}):
            out.append(finding("schema/type-widened", "info", f"{ptr}: type widened from {sorted(ot)} to {sorted(nt)}", uri, {"pointer": ptr, "from": sorted(ot), "to": sorted(nt)}))
        else:
            out.append(finding("schema/type-narrowed", "error", f"{ptr}: type changed from {sorted(ot)} to {sorted(nt)}", uri, {"pointer": ptr, "from": sorted(ot), "to": sorted(nt)}))
    oe, ne = o.get("enum"), n.get("enum")
    if isinstance(oe, list) and isinstance(ne, list):
        removed, added = [v for v in oe if v not in ne], [v for v in ne if v not in oe]
        if removed:
            out.append(finding("schema/enum-value-removed", "error", f"{ptr}: enum lost {removed}", uri, {"pointer": ptr, "removed": removed}))
        if added:
            out.append(finding("schema/enum-value-added", "warning", f"{ptr}: enum gained {added}; readers with exhaustive handling will not expect them", uri, {"pointer": ptr, "added": added}))
    elif ne is not None and oe is None:
        out.append(finding("schema/constraint-tightened", "error", f"{ptr}: enum introduced {ne}", uri, {"pointer": ptr, "keyword": "enum", "to": ne}))
    for kw in RAISE_TIGHTENS:
        if kw in o and kw in n and n[kw] > o[kw]:
            out.append(finding("schema/constraint-tightened", "error", f"{ptr}: {kw} raised from {o[kw]} to {n[kw]}", uri, {"pointer": ptr, "keyword": kw, "from": o[kw], "to": n[kw]}))
        elif kw in o and kw in n and n[kw] < o[kw]:
            out.append(finding("schema/constraint-loosened", "info", f"{ptr}: {kw} lowered from {o[kw]} to {n[kw]}", uri, {"pointer": ptr, "keyword": kw, "from": o[kw], "to": n[kw]}))
        elif kw not in o and kw in n:
            out.append(finding("schema/constraint-tightened", "error", f"{ptr}: {kw} introduced ({n[kw]})", uri, {"pointer": ptr, "keyword": kw, "to": n[kw]}))
        elif kw in o and kw not in n:
            out.append(finding("schema/constraint-loosened", "info", f"{ptr}: {kw} removed", uri, {"pointer": ptr, "keyword": kw, "from": o[kw]}))
    for kw in LOWER_TIGHTENS:
        if kw in o and kw in n and n[kw] < o[kw]:
            out.append(finding("schema/constraint-tightened", "error", f"{ptr}: {kw} lowered from {o[kw]} to {n[kw]}", uri, {"pointer": ptr, "keyword": kw, "from": o[kw], "to": n[kw]}))
        elif kw in o and kw in n and n[kw] > o[kw]:
            out.append(finding("schema/constraint-loosened", "info", f"{ptr}: {kw} raised from {o[kw]} to {n[kw]}", uri, {"pointer": ptr, "keyword": kw, "from": o[kw], "to": n[kw]}))
        elif kw not in o and kw in n:
            out.append(finding("schema/constraint-tightened", "error", f"{ptr}: {kw} introduced ({n[kw]})", uri, {"pointer": ptr, "keyword": kw, "to": n[kw]}))
        elif kw in o and kw not in n:
            out.append(finding("schema/constraint-loosened", "info", f"{ptr}: {kw} removed", uri, {"pointer": ptr, "keyword": kw, "from": o[kw]}))
    for kw in ("pattern", "format", "const"):
        if o.get(kw) != n.get(kw):
            if n.get(kw) is None:
                out.append(finding("schema/constraint-loosened", "info", f"{ptr}: {kw} removed", uri, {"pointer": ptr, "keyword": kw, "from": o.get(kw)}))
            else:
                out.append(finding("schema/constraint-tightened", "error", f"{ptr}: {kw} {'introduced' if o.get(kw) is None else 'changed'} to {n[kw]!r}", uri, {"pointer": ptr, "keyword": kw, "from": o.get(kw), "to": n[kw]}))
    if n.get("uniqueItems") and not o.get("uniqueItems"):
        out.append(finding("schema/constraint-tightened", "error", f"{ptr}: uniqueItems introduced", uri, {"pointer": ptr, "keyword": "uniqueItems", "to": True}))
    o_add, n_add = o.get("additionalProperties", True), n.get("additionalProperties", True)
    if o_add is not False and n_add is False:
        out.append(finding("schema/additional-properties-closed", "error", f"{ptr}: additionalProperties is now false; instances with extra keys are rejected", uri, {"pointer": ptr}))
    op, np_ = o.get("properties") or {}, n.get("properties") or {}
    oreq, nreq = set(o.get("required") or []), set(n.get("required") or [])
    for name in sorted(nreq - oreq):
        out.append(finding("schema/required-added", "error", f"{ptr}.{name}: property is now required", uri, {"pointer": f"{ptr}.{name}", "new": name not in op}))
    for name in sorted(oreq - nreq):
        out.append(finding("schema/required-removed", "info", f"{ptr}.{name}: property is no longer required", uri, {"pointer": f"{ptr}.{name}"}))
    for name, sch in op.items():
        if name not in np_:
            closed = n_add is False
            out.append(finding("schema/property-removed", "error" if closed else "warning",
                               f"{ptr}.{name}: property removed" + ("; additionalProperties is false, so old instances carrying it are rejected" if closed else "; readers expecting it get nothing"),
                               uri, {"pointer": f"{ptr}.{name}", "rejected": closed}))
        else:
            compare(od, nd, sch, np_[name], f"{ptr}.{name}", uri, out, seen)
    if "items" in o and "items" in n and isinstance(o["items"], dict) and isinstance(n["items"], dict):
        compare(od, nd, o["items"], n["items"], f"{ptr}.items", uri, out, seen)


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        sys.exit("ERROR: usage: diff_json_schema.py <old> <new>")
    old, new = load(args[0]), load(args[1])
    out, uri = [], Path(args[1]).name
    compare(old, new, old, new, "#", uri, out, set())
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order[r["level"]], r["properties"]["pointer"], r["ruleId"]))
    errors = sum(1 for r in out if r["level"] == "error")
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "json-schema-compat-check", "version": "0.1.0"},
                                         "properties": {"oldId": old.get("$id"), "newId": new.get("$id"), "breaking": errors, "backwardCompatible": errors == 0}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
