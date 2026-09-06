#!/usr/bin/env python3
"""Compare two OpenAPI 3.x documents and report the changes that break
existing clients, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    diff_openapi.py <old.(json|yaml)> <new.(json|yaml)>

Effect Ladder rung 1 (SDS-S-060): two files are read, nothing is
called. YAML input requires PyYAML; JSON needs nothing. `$ref`s into
`#/components/schemas/...` are resolved within each document; external
refs are left as opaque and compared by reference string.

A change is breaking when a request that was valid against the old
document can be rejected by the new one, or a response the old
document promised can be absent or differently typed. Rules emitted:

    api/path-removed            a path present in old is absent in new -> error
    api/operation-removed       a method on a kept path is gone -> error
    api/param-removed           a request parameter is gone (clients
                                still send it; servers may reject
                                unknown params) -> warning
    api/param-required-added    a new required parameter, or an
                                existing one made required -> error
    api/param-type-changed      a parameter's schema type changed -> error
    api/request-required-added  a request body property became
                                required -> error
    api/response-removed        a documented response status is gone
                                -> warning
    api/response-property-removed a property was removed from a
                                response schema -> error
    api/response-type-changed   a response property's type changed -> error
    api/enum-value-removed      an enum lost a value in a response
                                schema (clients may not handle new
                                ones; removed ones break switch
                                statements) -> warning
    api/operation-added         informational: a new path or method
                                -> info (never breaking)

Locations use the JSON-pointer-like path of the changed element in
`properties.pointer` (e.g. paths./orders/{id}.get.parameters.expand).
Whether a break is acceptable — an unreleased API, a coordinated
client deploy — is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; identical or purely additive documents yield
an empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on
stderr when a file cannot be read or parsed (spec-unparseable), or is
not an OpenAPI 3 document with `openapi` and `paths` (spec-invalid).
"""
import json
import sys
from pathlib import Path

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


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
    except Exception as e:  # noqa: BLE001 — any read/parse failure is the same failure code
        sys.exit(f"ERROR: could not read {path} (spec-unparseable): {e}")
    if not isinstance(doc, dict) or not str(doc.get("openapi", "")).startswith("3") or not isinstance(doc.get("paths"), dict):
        sys.exit(f"ERROR: {path} is not an OpenAPI 3 document with openapi and paths (spec-invalid)")
    return doc


def resolve(doc, schema, depth=0):
    """Inline local component refs (one level at a time, bounded)."""
    if not isinstance(schema, dict) or depth > 20:
        return schema
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        node = doc
        for part in ref[2:].split("/"):
            node = node.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(node, dict) else {}
        return resolve(doc, node, depth + 1)
    return schema


def schema_type(doc, schema):
    s = resolve(doc, schema)
    if not isinstance(s, dict):
        return None
    t = s.get("type")
    if t is None and "properties" in s:
        t = "object"
    if isinstance(t, list):
        t = "|".join(sorted(str(x) for x in t))
    fmt = s.get("format")
    return f"{t}:{fmt}" if fmt else t


def props_of(doc, schema):
    s = resolve(doc, schema)
    if not isinstance(s, dict):
        return {}, set()
    props = dict(s.get("properties") or {})
    required = set(s.get("required") or [])
    for part in s.get("allOf") or []:
        p, r = props_of(doc, part)
        props.update(p)
        required |= r
    return props, required


def params_of(doc, path_item, op):
    out = {}
    for p in (path_item.get("parameters") or []) + (op.get("parameters") or []):
        p = resolve(doc, p)
        if isinstance(p, dict) and "name" in p:
            out[(p.get("in", "query"), p["name"])] = p
    return out


def body_schema(doc, op):
    rb = resolve(doc, op.get("requestBody") or {})
    content = rb.get("content") or {}
    for ct in ("application/json", *content.keys()):
        if ct in content:
            return content[ct].get("schema")
    return None


def response_schema(doc, resp):
    resp = resolve(doc, resp or {})
    content = resp.get("content") or {}
    for ct in ("application/json", *content.keys()):
        if ct in content:
            return content[ct].get("schema")
    return None


def compare_schema(old_doc, new_doc, old_s, new_s, pointer, uri, results, response=True, seen=None):
    seen = seen or set()
    if pointer in seen or old_s is None or new_s is None:
        return
    seen.add(pointer)
    ot, nt = schema_type(old_doc, old_s), schema_type(new_doc, new_s)
    if ot and nt and ot != nt:
        results.append(finding("api/response-type-changed" if response else "api/param-type-changed", "error",
                               f"{pointer}: type changed from {ot} to {nt}", uri, {"pointer": pointer, "from": ot, "to": nt}))
        return
    o_r, n_r = resolve(old_doc, old_s), resolve(new_doc, new_s)
    if isinstance(o_r, dict) and isinstance(n_r, dict):
        oe, ne = o_r.get("enum"), n_r.get("enum")
        if isinstance(oe, list) and isinstance(ne, list):
            removed = [v for v in oe if v not in ne]
            if removed and response:
                results.append(finding("api/enum-value-removed", "warning",
                                       f"{pointer}: enum lost value(s) {removed}", uri, {"pointer": pointer, "removed": removed}))
        if o_r.get("type") == "array" or n_r.get("type") == "array":
            compare_schema(old_doc, new_doc, o_r.get("items"), n_r.get("items"), pointer + ".items", uri, results, response, seen)
    op_, oreq = props_of(old_doc, old_s)
    np_, nreq = props_of(new_doc, new_s)
    for name, sch in op_.items():
        if name not in np_:
            if response:
                results.append(finding("api/response-property-removed", "error",
                                       f"{pointer}.{name}: response property removed", uri, {"pointer": f"{pointer}.{name}"}))
        else:
            compare_schema(old_doc, new_doc, sch, np_[name], f"{pointer}.{name}", uri, results, response, seen)
    if not response:
        for name in sorted(nreq - oreq):
            results.append(finding("api/request-required-added", "error",
                                   f"{pointer}.{name}: request property is now required", uri, {"pointer": f"{pointer}.{name}"}))


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        sys.exit("ERROR: usage: diff_openapi.py <old> <new>")
    old, new = load(args[0]), load(args[1])
    uri = Path(args[1]).name
    results = []
    for path, old_item in old["paths"].items():
        new_item = new["paths"].get(path)
        if new_item is None:
            results.append(finding("api/path-removed", "error", f"path {path} removed", uri, {"pointer": f"paths.{path}"}))
            continue
        for m in METHODS:
            if m not in old_item:
                continue
            if m not in new_item:
                results.append(finding("api/operation-removed", "error", f"{m.upper()} {path} removed", uri, {"pointer": f"paths.{path}.{m}"}))
                continue
            o_op, n_op = old_item[m], new_item[m]
            base = f"paths.{path}.{m}"
            o_params, n_params = params_of(old, old_item, o_op), params_of(new, new_item, n_op)
            for key, p in o_params.items():
                ptr = f"{base}.parameters.{key[1]}"
                q = n_params.get(key)
                if q is None:
                    results.append(finding("api/param-removed", "warning", f"{ptr}: parameter removed", uri, {"pointer": ptr, "in": key[0]}))
                    continue
                if q.get("required") and not p.get("required"):
                    results.append(finding("api/param-required-added", "error", f"{ptr}: parameter is now required", uri, {"pointer": ptr, "in": key[0]}))
                compare_schema(old, new, p.get("schema"), q.get("schema"), ptr, uri, results, response=False)
            for key, q in n_params.items():
                if key not in o_params and q.get("required"):
                    ptr = f"{base}.parameters.{key[1]}"
                    results.append(finding("api/param-required-added", "error", f"{ptr}: new required parameter", uri, {"pointer": ptr, "in": key[0]}))
            compare_schema(old, new, body_schema(old, o_op), body_schema(new, n_op), f"{base}.requestBody", uri, results, response=False)
            o_resp, n_resp = o_op.get("responses") or {}, n_op.get("responses") or {}
            for status, r in o_resp.items():
                if status not in n_resp:
                    results.append(finding("api/response-removed", "warning", f"{base}: response {status} removed", uri, {"pointer": f"{base}.responses.{status}"}))
                    continue
                compare_schema(old, new, response_schema(old, r), response_schema(new, n_resp[status]), f"{base}.responses.{status}", uri, results, response=True)
    for path, new_item in new["paths"].items():
        old_item = old["paths"].get(path)
        for m in METHODS:
            if m in new_item and (old_item is None or m not in old_item):
                results.append(finding("api/operation-added", "info", f"{m.upper()} {path} added", uri, {"pointer": f"paths.{path}.{m}"}))
    order = {"error": 0, "warning": 1, "info": 2}
    results.sort(key=lambda r: (order[r["level"]], r["properties"]["pointer"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "openapi-breaking-change-check", "version": "0.1.0"},
                                         "properties": {"oldVersion": (old.get("info") or {}).get("version"), "newVersion": (new.get("info") or {}).get("version"),
                                                        "breaking": sum(1 for r in results if r["level"] == "error")}},
                                "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
