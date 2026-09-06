#!/usr/bin/env python3
"""Find dependencies pinned differently across the packages of a
workspace, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    find_version_drift.py <repo-path>

Effect Ladder rung 1 (SDS-S-060): manifests are read; no registry is
contacted. Workspaces and members are discovered as
affected-packages-finder does: package.json `workspaces`,
pnpm-workspace.yaml `packages`, or Cargo.toml [workspace] members;
each member's manifest supplies its name, version, and dependency
ranges (dependencies, devDependencies, peerDependencies; Cargo
dependencies, dev-dependencies, build-dependencies, with table forms
`{ version = "…" }` and path/workspace dependencies recognised).

Rules emitted:

    drift/version-mismatch      one external dependency required at two
                                or more different ranges across members
                                -> warning; properties list each range
                                with the members that use it and the
                                most common one
    drift/internal-mismatch     a member depends on another member at a
                                range that does not admit that member's
                                current version (and is not a
                                workspace:/path reference) -> error
                                (the build resolves a published copy,
                                not the sibling)
    drift/internal-unpinned     a member depends on another member with
                                a workspace:* / path reference while
                                other members pin an explicit range for
                                the same sibling -> info (mixed
                                strategies; pick one)

`tool.properties` carries the inventory: every external dependency
with its ranges and users, and the members with their versions.
Deciding which range wins — the newest, the one the root pins, the
one the most members use — is the skill's Analyze stage
(SDS-S-061).

Range admission is checked for the common forms only: exact,
^x.y.z, ~x.y.z, >=x.y.z, and `*`; anything else is reported as a
mismatch when it differs textually from the sibling's version. Prints
one finding-list; a consistent workspace yields an empty `results`
array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that
is not a directory (repo-invalid), no recognised workspace
(workspace-not-found), or a member manifest that does not parse
(manifest-malformed).
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


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
    return [d for pat in patterns if not pat.startswith("!") for d in sorted(root.glob(pat.rstrip("/"))) if d.is_dir()]


def discover(root):
    members = {}
    pkg, pnpm, cargo = root / "package.json", root / "pnpm-workspace.yaml", root / "Cargo.toml"
    patterns = []
    if pnpm.is_file():
        for line in pnpm.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*$", line)
            if m:
                patterns.append(m.group(1).strip())
    elif pkg.is_file():
        ws = load_json(pkg).get("workspaces")
        patterns = list(ws.get("packages") if isinstance(ws, dict) else (ws or []))
    for d in expand(root, patterns):
        m = d / "package.json"
        if not m.is_file():
            continue
        data = load_json(m)
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            for name, rng in (data.get(key) or {}).items():
                deps[name] = str(rng)
        members[data.get("name") or d.name] = {"dir": d.relative_to(root).as_posix(), "version": str(data.get("version", "")), "deps": deps, "uri": m.relative_to(root).as_posix()}
    if not members and cargo.is_file():
        ws = (load_toml(cargo).get("workspace") or {}).get("members") or []
        for d in expand(root, ws):
            m = d / "Cargo.toml"
            if not m.is_file():
                continue
            cd = load_toml(m)
            deps = {}
            for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                for name, spec in (cd.get(key) or {}).items():
                    if isinstance(spec, dict):
                        deps[name] = "workspace:*" if spec.get("workspace") else f"path:{spec['path']}" if spec.get("path") else str(spec.get("version", "*"))
                    else:
                        deps[name] = str(spec)
            members[(cd.get("package") or {}).get("name") or d.name] = {"dir": d.relative_to(root).as_posix(), "version": str((cd.get("package") or {}).get("version", "")), "deps": deps, "uri": m.relative_to(root).as_posix()}
    if not members:
        sys.exit("ERROR: no workspace found: need package.json workspaces, pnpm-workspace.yaml, or Cargo.toml [workspace] with members (workspace-not-found)")
    return members


def admits(rng, version):
    """Does the range admit the version? Common forms only; unknown forms compare textually."""
    if rng in ("*", "latest", "") or rng.startswith(("workspace:", "path:", "file:", "link:")):
        return True
    v = VER_RE.match(version)
    if not v:
        return rng == version
    vt = tuple(int(x) for x in v.groups())
    m = re.match(r"^([\^~>=]*)\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", rng)
    if not m:
        return rng == version
    op, parts = m.group(1), tuple(int(x) if x is not None else 0 for x in m.groups()[1:])
    if op == "" and rng.count(".") < 2:  # bare "1" or "1.2" in Cargo means ^1 / ^1.2
        op = "^"
    if op == "":
        return vt == parts
    if op == "^":
        return vt >= parts and (vt[0] == parts[0] if parts[0] > 0 else vt[:2] == parts[:2])
    if op == "~":
        return vt >= parts and vt[:2] == parts[:2]
    if op.startswith(">="):
        return vt >= parts
    return rng == version


def main():
    args = sys.argv[1:]
    if len(args) != 1:
        sys.exit("ERROR: usage: find_version_drift.py <repo-path>")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    members = discover(root)
    out = []
    external = defaultdict(lambda: defaultdict(list))  # dep -> range -> [members]
    internal_ranges = defaultdict(dict)  # sibling -> member -> range
    for name, m in sorted(members.items()):
        for dep, rng in sorted(m["deps"].items()):
            if dep in members:
                internal_ranges[dep][name] = rng
                if not admits(rng, members[dep]["version"]):
                    out.append(finding("drift/internal-mismatch", "error",
                                       f"{name} requires sibling {dep} at {rng!r} but the workspace copy is {members[dep]['version']}; the build resolves a published copy, not the sibling",
                                       m["uri"], {"package": name, "dependency": dep, "range": rng, "siblingVersion": members[dep]["version"]}))
            else:
                external[dep][rng].append(name)
    for dep, ranges in sorted(external.items()):
        if len(ranges) > 1:
            counts = Counter({r: len(users) for r, users in ranges.items()})
            common = counts.most_common(1)[0][0]
            first = members[sorted(ranges[common])[0]]["uri"]
            out.append(finding("drift/version-mismatch", "warning",
                               f"{dep} is required at {len(ranges)} different ranges: " + "; ".join(f"{r} ({', '.join(sorted(u))})" for r, u in sorted(ranges.items())) + f" — most common {common}",
                               first, {"dependency": dep, "ranges": {r: sorted(u) for r, u in ranges.items()}, "mostCommon": common}))
    for sib, users in sorted(internal_ranges.items()):
        kinds = {("reference" if r.startswith(("workspace:", "path:", "file:", "link:")) or r == "*" else "range") for r in users.values()}
        if len(kinds) > 1:
            out.append(finding("drift/internal-unpinned", "info",
                               f"{sib} is referenced by workspace/path in some members and pinned by range in others: " + ", ".join(f"{u}={r}" for u, r in sorted(users.items())) + "; pick one strategy",
                               members[sib]["uri"], {"dependency": sib, "users": dict(sorted(users.items()))}))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order[r["level"]], r["ruleId"], r["properties"].get("dependency", "")))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "cross-package-version-drift", "version": "0.1.0"},
                                         "properties": {"members": {n: m["version"] for n, m in sorted(members.items())},
                                                        "external": {d: {r: sorted(u) for r, u in rs.items()} for d, rs in sorted(external.items())},
                                                        "drifting": sum(1 for r in out if r["ruleId"] == "drift/version-mismatch")}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
