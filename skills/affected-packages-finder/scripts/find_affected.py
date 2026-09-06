#!/usr/bin/env python3
"""Map a set of changed files to the workspace packages they affect,
directly and through internal dependencies, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    find_affected.py <repo-path> --changed-files <list.txt>

Effect Ladder rung 1 (SDS-S-060): manifests are read; nothing is
built or run. The changed-file list is injected (SDS-S-065) — one
repository-relative path per line, as `git diff --name-only
<base>...<head>` prints it — so the skill never guesses the base.

Workspaces recognised by their manifests:
    npm / yarn   package.json `workspaces` (array or {packages: []}),
                 glob patterns like packages/*
    pnpm         pnpm-workspace.yaml `packages`
    Cargo        Cargo.toml [workspace] members
Each member's own manifest (package.json / Cargo.toml) gives its name
and its dependencies; a dependency whose name is another member is an
internal edge.

Rules emitted (one per affected package, ordered so that every
package comes after the packages it depends on — a build order):

    affected/direct        a changed file lies inside the package ->
                           info
    affected/dependent     the package depends, directly or
                           transitively, on a directly changed member
                           -> warning; properties.via is the chain
    affected/root-change   a changed file is a root manifest or
                           lockfile (package.json, pnpm-lock.yaml,
                           Cargo.lock, pnpm-workspace.yaml, Cargo.toml
                           at the root) -> warning on every package,
                           since the shared graph changed
    affected/unowned-file  a changed file lies in no package and is not
                           a root manifest -> info (docs, CI, tooling;
                           the reader decides whether it matters)

`tool.properties` carries the member list, the internal edges, and
`buildOrder`, the affected packages topologically sorted — what a CI
job would feed to `--filter`. Deciding whether an unowned change (a
shared lint config, a CI workflow) should count as affecting
everything is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; an empty change list yields an empty
`results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for
a path that is not a directory (repo-invalid), no recognised
workspace manifest (workspace-not-found), an unreadable change list
(changes-unreadable), or a member manifest that does not parse
(manifest-malformed).
"""
import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT_MANIFESTS = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "pnpm-workspace.yaml", "Cargo.toml", "Cargo.lock"}


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}], "properties": props}


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: {path} does not parse (manifest-malformed): {e}")


def load_toml(path):
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        sys.exit(f"ERROR: {path} does not parse (manifest-malformed): {e}")


def expand(root, patterns):
    dirs = []
    for pat in patterns:
        pat = pat.rstrip("/")
        if pat.startswith("!"):
            continue
        for d in sorted(root.glob(pat)):
            if d.is_dir():
                dirs.append(d)
    return dirs


def discover(root):
    """Return {name: {"dir": relpath, "deps": [names]}} for workspace members."""
    members = {}
    pkg = root / "package.json"
    pnpm = root / "pnpm-workspace.yaml"
    cargo = root / "Cargo.toml"
    patterns, kind = [], None
    if pnpm.is_file():
        kind = "pnpm"
        for line in pnpm.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*$", line)
            if m:
                patterns.append(m.group(1).strip())
    elif pkg.is_file():
        ws = load_json(pkg).get("workspaces")
        if isinstance(ws, dict):
            ws = ws.get("packages")
        if ws:
            kind, patterns = "npm", list(ws)
    if kind:
        for d in expand(root, patterns):
            m = d / "package.json"
            if not m.is_file():
                continue
            data = load_json(m)
            deps = set()
            for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                deps |= set((data.get(key) or {}).keys())
            members[data.get("name") or d.name] = {"dir": d.relative_to(root).as_posix(), "deps": deps, "kind": kind}
    if not members and cargo.is_file():
        data = load_toml(cargo)
        ws = (data.get("workspace") or {}).get("members") or []
        for d in expand(root, ws):
            m = d / "Cargo.toml"
            if not m.is_file():
                continue
            cd = load_toml(m)
            deps = set()
            for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                deps |= set((cd.get(key) or {}).keys())
            members[(cd.get("package") or {}).get("name") or d.name] = {"dir": d.relative_to(root).as_posix(), "deps": deps, "kind": "cargo"}
    if not members:
        sys.exit("ERROR: no workspace found: need package.json workspaces, pnpm-workspace.yaml, or Cargo.toml [workspace] with members (workspace-not-found)")
    for m in members.values():
        m["deps"] = sorted(d for d in m["deps"] if d in members)
    return members


def build_order(names, members):
    order, seen = [], set()

    def visit(n, stack):
        if n in seen:
            return
        if n in stack:
            return
        for d in members[n]["deps"]:
            if d in names:
                visit(d, stack | {n})
        seen.add(n)
        order.append(n)
    for n in sorted(names):
        visit(n, frozenset())
    return order


def main():
    args = sys.argv[1:]
    changed_path = None
    if "--changed-files" in args:
        i = args.index("--changed-files")
        if i + 1 >= len(args):
            sys.exit("ERROR: --changed-files requires a value")
        changed_path = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1 or changed_path is None:
        sys.exit("ERROR: usage: find_affected.py <repo-path> --changed-files <list.txt>")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    try:
        changed = [l.strip().replace("\\", "/") for l in changed_path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    except (OSError, UnicodeDecodeError) as e:
        sys.exit(f"ERROR: could not read change list {changed_path} (changes-unreadable): {e}")
    members = discover(root)
    by_dir = sorted(members.items(), key=lambda kv: -len(kv[1]["dir"]))  # longest dir first
    direct, root_changes, unowned = {}, [], []
    for f in changed:
        owner = next((name for name, m in by_dir if f == m["dir"] or f.startswith(m["dir"] + "/")), None)
        if owner:
            direct.setdefault(owner, []).append(f)
        elif "/" not in f and f in ROOT_MANIFESTS:
            root_changes.append(f)
        else:
            unowned.append(f)
    # reverse edges: who depends on whom
    dependents = {n: set() for n in members}
    for n, m in members.items():
        for d in m["deps"]:
            dependents[d].add(n)
    affected_via = {}
    frontier = list(direct)
    while frontier:
        n = frontier.pop()
        for dep in sorted(dependents[n]):
            if dep not in direct and dep not in affected_via:
                affected_via[dep] = (affected_via[n] if n in affected_via else [n]) + [dep]
                frontier.append(dep)
    out = []
    for name, files in sorted(direct.items()):
        out.append(finding("affected/direct", "info", f"{name}: {len(files)} changed file(s) inside {members[name]['dir']}", members[name]["dir"], {"package": name, "files": sorted(files)}))
    for name, via in sorted(affected_via.items()):
        out.append(finding("affected/dependent", "warning", f"{name} depends on changed package(s) via {' -> '.join(via)}", members[name]["dir"], {"package": name, "via": via}))
    if root_changes:
        for name in sorted(members):
            if name not in direct and name not in affected_via:
                out.append(finding("affected/root-change", "warning", f"{name}: root manifest change ({', '.join(root_changes)}) alters the shared graph; treat as affected", members[name]["dir"], {"package": name, "rootFiles": root_changes}))
    for f in unowned:
        out.append(finding("affected/unowned-file", "info", f"{f} lies in no package; decide whether it affects the build (CI, shared config) or nothing", f, {"file": f}))
    affected = set(direct) | set(affected_via) | (set(members) if root_changes else set())
    order = {"warning": 0, "info": 1}
    out.sort(key=lambda r: (order[r["level"]], r["ruleId"], r["properties"].get("package", r["properties"].get("file", ""))))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "affected-packages-finder", "version": "0.1.0"},
                                         "properties": {"members": {n: {"dir": m["dir"], "deps": m["deps"]} for n, m in sorted(members.items())},
                                                        "changedFiles": len(changed), "buildOrder": build_order(affected, members), "rootChanges": root_changes}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
