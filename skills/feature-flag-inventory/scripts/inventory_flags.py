#!/usr/bin/env python3
"""Inventory every feature-flag check in the code and compare it with the
flag configuration, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    inventory_flags.py <repo-path> --flags-file <flags.json|yaml> --as-of ISO
        [--stale-days N] [--patterns <patterns.json>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): files are read; no flag service is
called. Flag checks are found by call shape, configured in
assets/flag-patterns.json (default): a list of function or method
names whose first string argument is a flag name — is_enabled,
feature_enabled, flags.enabled, isEnabled, useFlag, variation,
getFlag … — matched in Python via `ast` and in JavaScript/TypeScript
via a pattern over .js/.mjs/.cjs/.ts/.tsx/.jsx files.

The configuration (--flags-file) is a JSON or YAML object
{"flags": [{"name", "enabled": bool, "rollout": 0-100?, "createdAt":
ISO?, "owner"?}]} — the shape most flag services export to, and easy
to derive from any of them. `--as-of` injects the clock (SDS-S-064)
and is REQUIRED: flag age is relative to now.

Rules emitted:

    flag/unregistered      checked in code, absent from the
                           configuration -> warning (the check reads
                           the default; nobody can turn it)
    flag/unreferenced      configured, checked nowhere -> info (stale
                           configuration, or read by another
                           repository)
    flag/fully-rolled-out  enabled at 100% (or enabled with no rollout)
                           for more than --stale-days (default 30)
                           and still checked -> warning (the flag is
                           now dead code; remove the check and the
                           flag)
    flag/permanently-off   disabled (or 0%) for more than --stale-days
                           and still checked -> info (the guarded code
                           is dead; delete it or ship it)
    flag/unowned           configured with no owner -> info

The run's `tool.properties` carries the inventory: every flag with
its check count, files, configured state, rollout, age in days, and
owner. Deciding which fully-rolled-out flag to remove first, and
whether a permanently-off flag guards an abandoned feature or a kill
switch, is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; a tree whose checks and configuration agree
and whose flags are young yields an empty `results` array
(SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that is
not a directory (repo-invalid), a Python file that does not parse
(source-unparseable), a flags file that cannot be read or lacks a
`flags` array (flags-unparseable), a patterns file that is not a list
of names (patterns-invalid), or a missing/invalid --as-of
(as-of-invalid).
"""
import ast
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv", "coverage"}
JS_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def parse_ts(value, what):
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        sys.exit(f"ERROR: {what} {value!r} is not an ISO-8601 timestamp (as-of-invalid)")
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def load_structured(path, code, key):
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: could not read {path} ({code}): {e}")
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        sys.exit(f"ERROR: {path} must be an object with a {key!r} array ({code})")
    return data[key]


def py_checks(tree, rel, names):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            f = node.func
            fname = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            if fname in names:
                yield node.args[0].value, rel, node.lineno


def js_checks(text, rel, names):
    rx = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\(\s*['\"]([A-Za-z0-9_.:-]+)['\"]")
    for m in rx.finditer(text):
        yield m.group(2), rel, text.count("\n", 0, m.start()) + 1


def main():
    args = sys.argv[1:]
    opts = {"--flags-file": None, "--as-of": None, "--stale-days": "30", "--patterns": None, "--exclude": ""}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or not opts["--flags-file"]:
        sys.exit("ERROR: usage: inventory_flags.py <repo-path> --flags-file F --as-of ISO [--stale-days N] [--patterns F] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    if not opts["--as-of"]:
        sys.exit("ERROR: --as-of is required; flag age is relative to now (as-of-invalid)")
    as_of = parse_ts(opts["--as-of"], "--as-of")
    try:
        stale_days = int(opts["--stale-days"])
    except ValueError:
        sys.exit("ERROR: --stale-days must be an integer (as-of-invalid)")
    patterns_path = opts["--patterns"] or str(Path(__file__).resolve().parent.parent / "assets" / "flag-patterns.json")
    try:
        names = json.loads(Path(patterns_path).read_text(encoding="utf-8"))["checkFunctions"]
        assert isinstance(names, list) and all(isinstance(n, str) for n in names) and names
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: patterns {patterns_path} must be {{checkFunctions: [names]}} (patterns-invalid): {e}")
    exclude = {x.strip() for x in opts["--exclude"].split(",") if x.strip()}
    flags = load_structured(opts["--flags-file"], "flags-unparseable", "flags")
    configured = {}
    for f in flags:
        if not isinstance(f, dict) or not f.get("name"):
            sys.exit(f"ERROR: every flag needs a name (flags-unparseable)")
        configured[f["name"]] = f

    checks = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        if p.suffix == ".py":
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            except SyntaxError as e:
                sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
            checks += list(py_checks(tree, rel.as_posix(), set(names)))
        elif p.suffix in JS_EXT:
            checks += list(js_checks(p.read_text(encoding="utf-8", errors="replace"), rel.as_posix(), set(names)))

    by_flag = defaultdict(list)
    for name, rel, line in checks:
        by_flag[name].append((rel, line))
    results, inventory = [], []
    for name in sorted(set(by_flag) | set(configured)):
        cs = sorted(by_flag.get(name, []))
        cfg = configured.get(name)
        age = None
        if cfg and cfg.get("createdAt"):
            age = (as_of - parse_ts(cfg["createdAt"], f"{name}.createdAt")).days
        rollout = cfg.get("rollout") if cfg else None
        enabled = bool(cfg.get("enabled")) if cfg else None
        inventory.append({"flag": name, "checks": len(cs), "files": sorted({c[0] for c in cs}), "configured": cfg is not None,
                          "enabled": enabled, "rollout": rollout, "ageDays": age, "owner": (cfg or {}).get("owner")})
        if cfg is None:
            results.append(finding("flag/unregistered", "warning", f"{name} is checked in {len(cs)} place(s) but not configured; the check always reads the default and nobody can turn it",
                                   cs[0][0], cs[0][1], {"flag": name, "checks": len(cs)}))
            continue
        if not cs:
            results.append(finding("flag/unreferenced", "info", f"{name} is configured but checked nowhere in the tree; stale, or read by another repository",
                                   Path(opts["--flags-file"]).name, None, {"flag": name}))
        elif age is not None and age > stale_days:
            if enabled and (rollout is None or rollout >= 100):
                results.append(finding("flag/fully-rolled-out", "warning", f"{name} has been enabled at 100% for {age} days and is still checked in {len(cs)} place(s); the flag is dead code — remove the checks and the flag",
                                       cs[0][0], cs[0][1], {"flag": name, "ageDays": age, "checks": len(cs)}))
            elif not enabled or rollout == 0:
                results.append(finding("flag/permanently-off", "info", f"{name} has been off for {age} days and is still checked; the guarded code is dead — delete it or ship it",
                                       cs[0][0], cs[0][1], {"flag": name, "ageDays": age, "checks": len(cs)}))
        if not cfg.get("owner"):
            results.append(finding("flag/unowned", "info", f"{name} has no owner; nobody is on the hook to remove it", Path(opts["--flags-file"]).name, None, {"flag": name}))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["ruleId"], r["properties"]["flag"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "feature-flag-inventory", "version": "0.1.0"},
                                         "properties": {"asOf": as_of.isoformat(), "staleDays": stale_days, "flags": inventory}},
                                "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
