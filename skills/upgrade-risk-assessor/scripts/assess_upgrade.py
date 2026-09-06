#!/usr/bin/env python3
"""Assess the risk of upgrading one Python dependency, as a decision-doc
(kit/shapes/decision-doc.schema.json).

Usage:
    assess_upgrade.py <repo-path> --package <name> --from <version> --to <version>
        [--changelog-file <path>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): the tree and the changelog file are
read, nothing is installed or run, no registry is queried — the
changelog is injected (SDS-S-065; fetch it first and pass the file).

Facts collected:
    jump      the semver relation between --from and --to: major,
              minor, patch, prerelease (target has a suffix), or
              downgrade
    usage     every module that imports the package (`import x`,
              `from x import y`, `from x.sub import z`) and every
              attribute path used through it (x.get, x.Session.mount),
              via `ast`
    breaking  changelog lines (between the --from and --to headings
              when the file has version headings, else the whole file)
              that say BREAKING, removed, renamed, dropped, deprecated,
              or no longer, and whether each names a symbol the tree
              uses

Rule table (first match wins):
    to < from                                      -> downgrade
    package not imported anywhere                  -> unused (upgrade
                                                      freely, or remove it)
    a breaking line names a used symbol            -> high
    major jump, or breaking lines without a
      changelog match to used symbols              -> medium
    prerelease target                              -> medium
    minor/patch jump, no breaking lines            -> low

`facts` carries the jump, the importing modules, the used symbols,
and the breaking lines with their symbol matches, so the reader sees
why. Judging what "medium" means for this repository — test coverage
of the importing modules, whether the package sits on a request path
— is the skill's Analyze stage (SDS-S-061).

Exit 1 with "ERROR: ..." on stderr for a path that is not a directory
(repo-invalid), a version that is not semver-like (version-invalid), a
missing/unreadable changelog file (changelog-unreadable), or a source
file that does not parse (source-unparseable).
"""
import ast
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?([-.+]?[0-9A-Za-z.+-]*)?$")
BREAKING_RE = re.compile(r"\b(BREAKING|breaking change|removed?|renamed?|dropped?|deprecated|no longer|incompatible)\b", re.I)
HEADING_RE = re.compile(r"^#{1,4}\s*\[?v?(\d+\.\d+(?:\.\d+)?)", re.M)
OPTIONS = ["low", "medium", "high", "downgrade", "unused"]


def parse_version(v, what):
    m = VERSION_RE.match(v.strip())
    if not m:
        sys.exit(f"ERROR: {what} {v!r} is not a version (version-invalid)")
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)), bool(m.group(4))


def jump(frm, to):
    (a, pre_a), (b, pre_b) = frm, to
    if b < a:
        return "downgrade"
    if pre_b:
        return "prerelease"
    if b[0] > a[0]:
        return "major"
    if b[1] > a[1]:
        return "minor"
    return "patch"


def usage(root, package, exclude):
    modules, symbols = [], set()
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
        aliases, imported = {}, False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == package or a.name.startswith(package + "."):
                        imported = True
                        aliases[a.asname or a.name.split(".")[0]] = a.name
            elif isinstance(node, ast.ImportFrom) and node.module and (node.module == package or node.module.startswith(package + ".")):
                imported = True
                for a in node.names:
                    symbols.add(f"{node.module}.{a.name}")
                    aliases[a.asname or a.name] = f"{node.module}.{a.name}"
        if not imported:
            continue
        modules.append(rel.as_posix())

        def chain(node):
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id in aliases:
                return ".".join([aliases[cur.id]] + list(reversed(parts)))
            return None

        # one hop of flow: `s = requests.Session(...)` makes `s.mount` a use of requests.Session.mount
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                value = node.value.func if isinstance(node.value, ast.Call) else node.value
                sym = chain(value) if isinstance(value, ast.Attribute) else (aliases.get(value.id) if isinstance(value, ast.Name) else None)
                if sym and node.targets[0].id not in aliases:
                    aliases[node.targets[0].id] = sym
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                sym = chain(node)
                if sym:
                    symbols.add(sym)
    return modules, sorted(symbols)


def names_symbol(line, symbol):
    """A line names a used symbol when its dotted tail appears as a code token:
    `Session.mount` for a multi-part symbol; a single name only when backticked
    or followed by `(` or `.` (so `get` does not match get_encodings)."""
    tail = symbol.split(".")[1:]
    if not tail:
        return False
    if len(tail) >= 2:
        return re.search(r"(?<![\w.])" + re.escape(".".join(tail[-2:])) + r"(?![\w])", line) is not None
    return re.search(r"(?<![\w.])" + re.escape(tail[0]) + r"(?=[(.`])", line) is not None or re.search(r"`" + re.escape(tail[0]) + r"`", line) is not None


def breaking_lines(text, frm_s, to_s):
    heads = list(HEADING_RE.finditer(text))
    if heads:
        def key(v):
            return tuple(int(x) for x in v.split("."))
        lo, hi = key(frm_s), key(to_s)
        chunks = []
        for i, h in enumerate(heads):
            v = key(h.group(1))
            if lo < v <= hi or (v > hi and False):
                end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
                chunks.append(text[h.start():end])
        text = "\n".join(chunks)
    return [l.strip() for l in text.splitlines() if BREAKING_RE.search(l)]


def main():
    args = sys.argv[1:]
    opts = {"--package": None, "--from": None, "--to": None, "--changelog-file": None, "--exclude": ""}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or not (opts["--package"] and opts["--from"] and opts["--to"]):
        sys.exit("ERROR: usage: assess_upgrade.py <repo-path> --package NAME --from V --to V [--changelog-file F] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    frm, to = parse_version(opts["--from"], "--from"), parse_version(opts["--to"], "--to")
    j = jump(frm, to)
    exclude = {x.strip() for x in opts["--exclude"].split(",") if x.strip()}
    package = opts["--package"].replace("-", "_")
    modules, symbols = usage(root, package, exclude)
    lines = []
    if opts["--changelog-file"]:
        try:
            text = Path(opts["--changelog-file"]).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: could not read changelog {opts['--changelog-file']} (changelog-unreadable): {e}")
        frm_s = ".".join(str(x) for x in frm[0]); to_s = ".".join(str(x) for x in to[0])
        for l in breaking_lines(text, frm_s, to_s):
            lines.append({"line": l[:200], "usedSymbols": [s for s in symbols if names_symbol(l, s)]})
    matched = [b for b in lines if b["usedSymbols"]]
    drivers = [f"jump: {opts['--from']} -> {opts['--to']} ({j})",
               f"usage: imported by {len(modules)} module(s); {len(symbols)} symbol(s) used",
               f"changelog: {len(lines)} breaking line(s), {len(matched)} naming a used symbol" if opts["--changelog-file"] else "changelog: not supplied"]
    if j == "downgrade":
        chosen, why = "downgrade", "the target is older than the current version; this is a rollback, assess the reason for it instead"
    elif not modules:
        chosen, why = "unused", f"nothing in the tree imports {package}; upgrade freely, or remove the dependency"
    elif matched:
        chosen, why = "high", f"{len(matched)} breaking change(s) name symbols this tree uses: " + "; ".join(", ".join(b["usedSymbols"]) for b in matched[:3])
    elif j == "major":
        chosen, why = "medium", "a major version jump" + ("; the changelog's breaking lines name nothing this tree uses, but a major bump may break without saying so" if lines else "; no changelog was supplied, so the breaking changes are unknown" if not opts["--changelog-file"] else "; the changelog lists no breaking change, which is unusual for a major bump")
    elif lines:
        chosen, why = "medium", f"{len(lines)} breaking line(s) in the changelog; none names a used symbol, but read them"
    elif j == "prerelease":
        chosen, why = "medium", "the target is a prerelease; its API may still move"
    else:
        chosen, why = "low", f"a {j} bump with no breaking change recorded" + ("" if opts["--changelog-file"] else " (no changelog supplied; the claim rests on semver alone)")
    print(json.dumps({
        "status": "accepted",
        "contextAndProblemStatement": f"How risky is upgrading {opts['--package']} from {opts['--from']} to {opts['--to']} for this repository?",
        "decisionDrivers": drivers,
        "consideredOptions": OPTIONS,
        "decisionOutcome": {"chosenOption": chosen, "justification": why},
        "consequences": {"positive": [], "negative": [f"used symbol {s} is named in: {b['line'][:80]}" for b in matched for s in b["usedSymbols"]]},
        "confirmation": "Run the importing modules' tests against the new version in a branch before merging the bump.",
        "facts": {"package": opts["--package"], "jump": j, "importingModules": modules, "usedSymbols": symbols, "breakingLines": lines},
    }, indent=2))


if __name__ == "__main__":
    main()
