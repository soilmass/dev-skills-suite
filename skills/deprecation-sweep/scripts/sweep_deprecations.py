#!/usr/bin/env python3
"""Find every use of a deprecated symbol and every DeprecationWarning the
tests emitted, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    sweep_deprecations.py <repo-path> [--deprecations <file.json>] [--warnings-log <file>]
        [--target-version <v>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): files are read; nothing is
imported or run. Two sources, either or both:

    --deprecations   {"deprecations": [{"symbol": "requests.Session.mount",
                     "replacement": "…", "removedIn": "3.0.0", "since": "2.32.0",
                     "note"?}]} — a maintained list, or one derived from
                     a changelog by upgrade-risk-assessor. A symbol is
                     `package.attr.path`; the sweep resolves imports and
                     aliases with `ast` (import x as y, from x import y)
                     and one hop of assignment (s = x.Session(); s.mount).
    --warnings-log   a captured test or run log; every line of the shape
                     `<path>:<line>: DeprecationWarning: <text>` (Python's
                     warnings format, also PendingDeprecationWarning and
                     FutureWarning) whose path is inside the tree is a
                     finding.

Rules emitted:

    deprecation/usage             a listed symbol is used -> warning;
                                  error when --target-version is given
                                  and removedIn <= target (the upgrade
                                  will break here)
    deprecation/warning-emitted   a DeprecationWarning line from the log
                                  points into the tree -> warning
                                  (error if the text says "removed in"
                                  a version <= target)
    deprecation/warning-external  a DeprecationWarning line whose path is
                                  outside the tree (site-packages) ->
                                  info (a dependency's problem, not ours;
                                  still worth an upgrade)

Properties carry the symbol, replacement, removal version, and the
log text. Deciding order — what to fix before the upgrade versus
what can wait — is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; a tree with no deprecated use yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a path that is not a directory (repo-invalid), a deprecations
file that is not the expected shape (deprecations-unparseable), an
unreadable log (log-unreadable), a Python file that does not parse
(source-unparseable), or neither source given (no-source).
"""
import ast
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
WARN_RE = re.compile(r"^(?P<path>[^:\s]+\.py):(?P<line>\d+):\s*(?P<kind>(?:Pending)?DeprecationWarning|FutureWarning):\s*(?P<text>.*)$")
REMOVED_RE = re.compile(r"removed?\s+in\s+(?:version\s+)?v?(\d+(?:\.\d+)*)", re.I)


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) if v else None


def symbol_uses(tree, rel, symbols):
    """Yield (symbol, line) for every use of a listed dotted symbol."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"

    def chain(node):
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name) and cur.id in aliases:
            return ".".join([aliases[cur.id]] + list(reversed(parts)))
        return None

    for node in ast.walk(tree):  # one hop: s = pkg.Session() -> s.<attr> is pkg.Session.<attr>
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = node.value.func if isinstance(node.value, ast.Call) else node.value
            sym = chain(value) if isinstance(value, ast.Attribute) else (aliases.get(value.id) if isinstance(value, ast.Name) else None)
            if sym and node.targets[0].id not in aliases:
                aliases[node.targets[0].id] = sym
    for node in ast.walk(tree):
        sym = None
        if isinstance(node, ast.Attribute):
            sym = chain(node)
        elif isinstance(node, ast.Name) and node.id in aliases and not isinstance(getattr(node, "ctx", None), ast.Store):
            sym = aliases[node.id]
        if sym and sym in symbols:
            yield sym, node.lineno


def main():
    args = sys.argv[1:]
    opts = {"--deprecations": None, "--warnings-log": None, "--target-version": None, "--exclude": ""}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: sweep_deprecations.py <repo-path> [--deprecations F] [--warnings-log F] [--target-version V] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    if not opts["--deprecations"] and not opts["--warnings-log"]:
        sys.exit("ERROR: give --deprecations and/or --warnings-log; there is nothing to sweep for (no-source)")
    target = vkey(opts["--target-version"]) if opts["--target-version"] else None
    exclude = {x.strip() for x in opts["--exclude"].split(",") if x.strip()}
    out = []

    deprecations = {}
    if opts["--deprecations"]:
        try:
            data = json.loads(Path(opts["--deprecations"]).read_text(encoding="utf-8"))
            for d in data["deprecations"]:
                deprecations[d["symbol"]] = d
        except Exception as e:  # noqa: BLE001
            sys.exit(f"ERROR: {opts['--deprecations']} must be {{deprecations: [{{symbol, replacement?, removedIn?}}]}} (deprecations-unparseable): {e}")
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(root)
            if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            except SyntaxError as e:
                sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
            seen = set()
            for sym, line in symbol_uses(tree, rel.as_posix(), set(deprecations)):
                if (sym, line) in seen:
                    continue
                seen.add((sym, line))
                d = deprecations[sym]
                imminent = target is not None and d.get("removedIn") and vkey(d["removedIn"]) <= target
                out.append(finding("deprecation/usage", "error" if imminent else "warning",
                                   f"{sym} is deprecated" + (f" since {d['since']}" if d.get("since") else "") + (f", removed in {d['removedIn']}" if d.get("removedIn") else "")
                                   + (f"; use {d['replacement']}" if d.get("replacement") else "") + ("; the target version removes it" if imminent else ""),
                                   rel.as_posix(), line, {"symbol": sym, "replacement": d.get("replacement"), "removedIn": d.get("removedIn"), "imminent": bool(imminent)}))

    if opts["--warnings-log"]:
        try:
            log = Path(opts["--warnings-log"]).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            sys.exit(f"ERROR: could not read log {opts['--warnings-log']} (log-unreadable): {e}")
        seen = set()
        for raw in log.splitlines():
            m = WARN_RE.match(raw.strip())
            if not m:
                continue
            path, line, text = m.group("path"), int(m.group("line")), m.group("text").strip()
            key = (path, line, text)
            if key in seen:
                continue
            seen.add(key)
            rel = None
            try:
                rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                # a relative path may be relative to the tree; an absolute one outside it stays external
                if not Path(path).is_absolute() and (root / path).is_file():
                    rel = Path(path).as_posix()
            if rel is None:
                out.append(finding("deprecation/warning-external", "info", f"{m.group('kind')} from outside the tree ({path}:{line}): {text[:100]}; a dependency's problem, still worth its upgrade",
                                   path, line, {"kind": m.group("kind"), "text": text[:200]}))
                continue
            rm = REMOVED_RE.search(text)
            imminent = target is not None and rm is not None and vkey(rm.group(1)) <= target
            out.append(finding("deprecation/warning-emitted", "error" if imminent else "warning",
                               f"{m.group('kind')}: {text[:120]}" + ("; the target version removes it" if imminent else ""),
                               rel, line, {"kind": m.group("kind"), "text": text[:200], "removedIn": rm.group(1) if rm else None, "imminent": bool(imminent)}))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"].get("region", {}).get("startLine", 0), r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "deprecation-sweep", "version": "0.1.0"},
                                         "properties": {"targetVersion": opts["--target-version"], "listedSymbols": sorted(deprecations), "blocking": sum(1 for r in out if r["level"] == "error")}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
