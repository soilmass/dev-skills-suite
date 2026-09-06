#!/usr/bin/env python3
"""Inventory every logging call in a Python tree and report the drift a
log taxonomy would fix, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    inventory_logs.py <repo-path> [--exclude dir,dir] [--conventions <file>]

Effect Ladder rung 1 (SDS-S-060): `ast` only, nothing is imported or
run. A logging call is `<name>.<level>(...)` where <name> is
logging/logger/log/LOGGER/_log/structlog-style `log` and <level> is
debug/info/warning/warn/error/critical/exception. From each call the
script takes the level, the message (a constant template, or the kind
of interpolation used), the fields (keyword arguments, `extra={...}`
keys, and `%s`-style placeholders), and the enclosing except handler.

Field names are mapped onto canonical attribute names through
assets/semantic-conventions.json (OpenTelemetry semantic conventions
where one exists). Rules emitted:

    log/inconsistent-field-name  one canonical attribute logged under
                                 two or more spellings across the
                                 tree -> warning; properties list the
                                 variants with counts and the
                                 canonical name
    log/level-mismatch           a message that says failed/error/
                                 cannot/unable/exception at debug or
                                 info, or started/completed/succeeded
                                 at error or critical -> warning
    log/sensitive-field          a field whose name is in the
                                 conventions' sensitive list -> warning
    log/interpolated-message     the message is an f-string, %-format,
                                 .format() call, or concatenation ->
                                 info (values belong in fields; the
                                 message should be a constant template
                                 so one event has one shape)
    log/exception-without-traceback an error/critical call inside an
                                 except handler that is not
                                 .exception() and has no exc_info ->
                                 info

The run's `tool.properties` carries the inventory: calls per level,
every field name with its count and canonical mapping, and the set of
constant message templates. Designing the taxonomy — which canonical
names to adopt, what every event must carry — is the skill's Analyze
stage (SDS-S-061).

Prints one finding-list; a tree with consistent logging yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a path that is not a directory (repo-invalid), a file that does
not parse (source-unparseable), or a conventions file that is not the
expected shape (conventions-invalid).
"""
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
LOGGER_NAMES = {"logging", "logger", "log", "LOGGER", "LOG", "_log", "_logger", "self.logger", "self.log"}
LEVELS = {"debug": "debug", "info": "info", "warning": "warning", "warn": "warning", "error": "error", "critical": "critical", "exception": "error"}
FAILY_RE = re.compile(r"\b(fail(ed|ure|s)?|error|exception|cannot|can't|unable|refused|denied|crash(ed)?|timed out|timeout)\b", re.I)
HAPPY_RE = re.compile(r"\b(started|starting|completed|succeeded|success(ful)?|finished|ok|healthy)\b", re.I)


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def load_conventions(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        canon = {v: k for k, vs in data["canonical"].items() for v in vs}
        for k in data["canonical"]:
            canon[k] = k
        sensitive = set(data["sensitive"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        sys.exit(f"ERROR: conventions {path} is not a {{canonical: {{name: [variants]}}, sensitive: [...]}} object (conventions-invalid): {e}")
    return canon, sensitive


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def message_kind(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "constant", node.value
    if isinstance(node, ast.JoinedStr):
        return "f-string", "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant):
        return "percent-format", node.left.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return "concatenation", ""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format" and isinstance(node.func.value, ast.Constant):
        return "format-call", node.func.value.value
    return "dynamic", ""


def collect(tree, rel):
    """Yield one record per logging call, with the enclosing except handler if any."""
    handlers = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            for sub in ast.walk(node):
                handlers[id(sub)] = node
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        base = dotted(node.func.value)
        method = node.func.attr
        if base not in LOGGER_NAMES or method not in LEVELS:
            continue
        kind, template = message_kind(node.args[0]) if node.args else ("dynamic", "")
        fields = []
        exc_info = method == "exception"
        for kw in node.keywords:
            if kw.arg == "exc_info":
                exc_info = True
            elif kw.arg == "extra" and isinstance(kw.value, ast.Dict):
                fields += [k.value for k in kw.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            elif kw.arg and kw.arg not in ("stack_info", "stacklevel"):
                fields.append(kw.arg)
        yield {"uri": rel, "line": node.lineno, "level": LEVELS[method], "method": method, "messageKind": kind,
               "template": template, "fields": fields, "inExcept": id(node) in handlers, "excInfo": exc_info}


def main():
    args = sys.argv[1:]
    exclude = set()
    conventions = str(Path(__file__).resolve().parent.parent / "assets" / "semantic-conventions.json")
    for flag in ("--exclude", "--conventions"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            if flag == "--exclude":
                exclude = {x.strip() for x in args[i + 1].split(",") if x.strip()}
            else:
                conventions = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: inventory_logs.py <repo-path> [--exclude dir,dir] [--conventions <file>]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    canon, sensitive = load_conventions(conventions)

    calls = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
        calls += list(collect(tree, rel.as_posix()))

    results = []
    field_counts = Counter()
    by_canonical = defaultdict(Counter)
    for c in calls:
        for f in c["fields"]:
            field_counts[f] += 1
            by_canonical[canon.get(f, f)][f] += 1
        text = c["template"]
        if c["level"] in ("debug", "info") and FAILY_RE.search(text):
            results.append(finding("log/level-mismatch", "warning",
                                   f"{c['level']} message reads like a failure: {text[:60]!r}; a reader filtering on error will not see it",
                                   c["uri"], c["line"], {"level": c["level"], "template": text[:160]}))
        elif c["level"] in ("error", "critical") and HAPPY_RE.search(text) and not FAILY_RE.search(text):
            results.append(finding("log/level-mismatch", "warning",
                                   f"{c['level']} message reads like normal operation: {text[:60]!r}; it will page someone",
                                   c["uri"], c["line"], {"level": c["level"], "template": text[:160]}))
        for f in c["fields"]:
            if f in sensitive:
                results.append(finding("log/sensitive-field", "warning",
                                       f"field {f!r} is logged; secrets and personal identifiers never belong in a log line",
                                       c["uri"], c["line"], {"field": f}))
        if c["messageKind"] not in ("constant", "dynamic"):
            results.append(finding("log/interpolated-message", "info",
                                   f"message is built by {c['messageKind']}; move the values into fields so every occurrence of this event has one template",
                                   c["uri"], c["line"], {"messageKind": c["messageKind"], "template": text[:160]}))
        if c["inExcept"] and c["level"] in ("error", "critical") and not c["excInfo"]:
            results.append(finding("log/exception-without-traceback", "info",
                                   f"{c['level']} logged inside an except handler without the traceback; use .exception() or exc_info=True",
                                   c["uri"], c["line"], {"level": c["level"]}))
    for canonical, variants in sorted(by_canonical.items()):
        if len(variants) >= 2:
            first = min(calls, key=lambda c: (c["uri"], c["line"]))
            results.append(finding("log/inconsistent-field-name", "warning",
                                   f"{canonical} is logged as {', '.join(f'{v} ({n})' for v, n in variants.most_common())}; one attribute, one name",
                                   first["uri"], first["line"], {"canonical": canonical, "variants": dict(variants)}))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["ruleId"], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"]))
    inventory = {"calls": len(calls),
                 "levels": dict(Counter(c["level"] for c in calls)),
                 "fields": [{"name": f, "count": n, "canonical": canon.get(f, f)} for f, n in field_counts.most_common()],
                 "templates": sorted({c["template"] for c in calls if c["messageKind"] == "constant"})}
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "log-taxonomy-designer", "version": "0.1.0"}, "properties": inventory},
                                "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
