#!/usr/bin/env python3
"""Check a repository's CODEOWNERS file against the tree, as a
finding-list (kit/shapes/finding-list.schema.json).

Usage:
    check_codeowners.py <repo-path> [--members <members.txt>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): the file and the tree are read;
GitHub is not contacted. The file is located as GitHub does
(.github/CODEOWNERS, CODEOWNERS, docs/CODEOWNERS; first found wins)
and parsed with GitHub's rules: one pattern per line followed by
owners, `#` comments, last matching rule wins, gitignore-style
patterns (`*`, `**`, leading `/` anchors at the root, trailing `/`
means a directory, a pattern with no slash matches at any depth).

Rules emitted:

    owners/unowned-path         a top-level directory or file no rule
                                matches -> warning (nobody is requested
                                for review there); reported per
                                top-level entry, never per file
    owners/rule-matches-nothing a rule whose pattern matches no path in
                                the tree -> info (stale: the path moved
                                or was deleted)
    owners/no-owner             a rule line with a pattern and no owner
                                -> warning (GitHub treats it as
                                "no owner", which silently unassigns)
    owners/invalid-owner        an owner that is not @user, @org/team,
                                or an email -> warning
    owners/unknown-owner        with --members (one handle per line):
                                an owner not in the list -> warning
    owners/shadowed-rule        every path a rule matches is also
                                matched by a later rule -> info (last
                                match wins; the earlier rule never
                                applies)
    owners/missing-file         no CODEOWNERS found -> info

Properties carry the line number, pattern, and owners. Deciding
whether an unowned path needs an owner or is deliberately shared,
and who should own it, is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; a complete, current file yields an empty
`results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a
path that is not a directory (repo-invalid) or an unreadable members
file (members-unreadable).
"""
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
OWNER_RE = re.compile(r"^(@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:/[A-Za-z0-9._-]+)?|[^@\s]+@[^@\s]+\.[^@\s]+)$")


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def pattern_to_regex(pat):
    """gitignore-style CODEOWNERS pattern -> compiled regex over posix paths (files and 'dir/' entries)."""
    anchored = pat.startswith("/")
    p = pat.lstrip("/")
    dir_only = p.endswith("/")
    p = p.rstrip("/")
    if not anchored and "/" not in p:
        prefix = r"(?:.*/)?"
    else:
        prefix = ""
    out = ""
    i = 0
    while i < len(p):
        c = p[i]
        if p.startswith("**/", i):
            out += r"(?:.*/)?"; i += 3; continue
        if p.startswith("**", i):
            out += r".*"; i += 2; continue
        if c == "*":
            out += r"[^/]*"
        elif c == "?":
            out += r"[^/]"
        else:
            out += re.escape(c)
        i += 1
    if dir_only:
        return re.compile(rf"^{prefix}{out}/.*$")
    return re.compile(rf"^{prefix}{out}(?:/.*)?$")


def parse(text):
    rules = []
    for ln, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("#") else ""
        if not line:
            continue
        parts = line.split()
        rules.append({"line": ln, "pattern": parts[0], "owners": parts[1:], "regex": pattern_to_regex(parts[0])})
    return rules


def main():
    args = sys.argv[1:]
    members_path, exclude = None, set()
    for flag in ("--members", "--exclude"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            if flag == "--members":
                members_path = Path(args[i + 1])
            else:
                exclude = {x.strip() for x in args[i + 1].split(",") if x.strip()}
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: check_codeowners.py <repo-path> [--members <file>] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    members = None
    if members_path:
        try:
            members = {l.strip() for l in members_path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
        except (OSError, UnicodeDecodeError) as e:
            sys.exit(f"ERROR: could not read members file {members_path} (members-unreadable): {e}")
    out = []
    co = next((root / l for l in LOCATIONS if (root / l).is_file()), None)
    files = [p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if p.is_file() and not any(part in SKIP_DIRS or part in exclude for part in p.relative_to(root).parts)]
    if co is None:
        out.append(finding("owners/missing-file", "info", "no CODEOWNERS found (.github/CODEOWNERS, CODEOWNERS, docs/CODEOWNERS); no review is auto-requested anywhere", "CODEOWNERS", None, {"filesInTree": len(files)}))
        rules = []
        uri = "CODEOWNERS"
    else:
        uri = co.relative_to(root).as_posix()
        rules = parse(co.read_text(encoding="utf-8"))
        files = [f for f in files if f != uri]  # the ownership file itself is not a path to own
    matches = {r["line"]: {f for f in files if r["regex"].match(f)} for r in rules}
    owner_of = {}
    for r in rules:  # last match wins
        for f in matches[r["line"]]:
            owner_of[f] = r
    for r in rules:
        if not r["owners"]:
            out.append(finding("owners/no-owner", "warning", f"line {r['line']}: {r['pattern']} has no owner; GitHub treats this as unassigning the paths it matches", uri, r["line"], {"pattern": r["pattern"]}))
        for o in r["owners"]:
            if not OWNER_RE.match(o):
                out.append(finding("owners/invalid-owner", "warning", f"line {r['line']}: {o!r} is not @user, @org/team, or an email", uri, r["line"], {"pattern": r["pattern"], "owner": o}))
            elif members is not None and o not in members:
                out.append(finding("owners/unknown-owner", "warning", f"line {r['line']}: {o} is not in the members list; review requests to it fail silently", uri, r["line"], {"pattern": r["pattern"], "owner": o}))
        if not matches[r["line"]]:
            out.append(finding("owners/rule-matches-nothing", "info", f"line {r['line']}: {r['pattern']} matches no path in the tree; the path moved or was deleted", uri, r["line"], {"pattern": r["pattern"]}))
        elif all(owner_of[f] is not r for f in matches[r["line"]]):
            later = sorted({owner_of[f]["line"] for f in matches[r["line"]]})
            out.append(finding("owners/shadowed-rule", "info", f"line {r['line']}: every path {r['pattern']} matches is also matched by a later rule (line {', '.join(map(str, later))}); last match wins, so this rule never applies", uri, r["line"], {"pattern": r["pattern"], "shadowedBy": later}))
    top = {}
    for f in files:
        head = f.split("/", 1)[0]
        top.setdefault(head, []).append(f)
    for head, fs in sorted(top.items()):
        unowned = [f for f in fs if f not in owner_of]
        if rules and unowned and head not in ("CODEOWNERS",):
            out.append(finding("owners/unowned-path", "warning", f"{head}{'/' if len(fs) > 1 or '/' in fs[0] else ''}: {len(unowned)} of {len(fs)} file(s) match no rule; nobody is requested for review there",
                               uri, None, {"path": head, "unownedFiles": len(unowned), "files": len(fs), "examples": unowned[:3]}))
    order = {"warning": 0, "info": 1}
    out.sort(key=lambda r: (order[r["level"]], r["ruleId"], r["locations"][0]["physicalLocation"].get("region", {}).get("startLine", 0), r["properties"].get("path", r["properties"].get("pattern", ""))))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "codeowners-check", "version": "0.1.0"},
                                         "properties": {"codeowners": uri if co else None, "rules": len(rules), "files": len(files), "ownedFiles": len(owner_of),
                                                        "owners": sorted({o for r in rules for o in r["owners"]})}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
