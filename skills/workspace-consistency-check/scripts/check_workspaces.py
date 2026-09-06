#!/usr/bin/env python3
"""Check a monorepo's declared workspace members against what is
actually on disk, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    check_workspaces.py <repo-path>

Effect Ladder rung 1 (SDS-S-060): manifests are read; nothing is
modified and no registry is contacted.

The workspace kind is detected in this order, the first one found
wins: npm/yarn (`package.json` with a `workspaces` array or a
`{packages: [...]}` object), pnpm (`pnpm-workspace.yaml`'s `packages`
list), Cargo (`Cargo.toml`'s `[workspace] members`), Go (`go.work`'s
`use` block or `use ./x` lines), and uv (`pyproject.toml`'s
`[tool.uv.workspace] members`). No recognised declaration found is not
a failure: an empty finding-list with `tool.properties.kind` `null`
(SDS-C-033).

Rules emitted, once a workspace is recognised:

    mono/member-missing            a declared member glob or path that
                                    matches no directory holding a
                                    manifest -> error, at the root
                                    manifest
    mono/orphan-package            a manifest one level under
                                    packages/, apps/, libs/, crates/,
                                    or services/ that no declaration
                                    covers -> warning, at that manifest
    mono/duplicate-name            two members share a package name
                                    -> error, at the first member
                                    manifest (alphabetically)
    mono/internal-version-mismatch a member depends on a sibling at a
                                    range the sibling's own version
                                    does not satisfy -> warning, at the
                                    dependent member's manifest
    mono/mixed-lockfiles           more than one of package-lock.json,
                                    yarn.lock, pnpm-lock.yaml,
                                    bun.lockb at the root -> warning,
                                    at the first lockfile
                                    (alphabetically)
    mono/nested-lockfile           a member directory with its own
                                    lockfile -> info, at that lockfile

`tool.properties` carries `kind`, the resolved member count, the
declared-entry count, the orphan count, and the root lockfiles found.
Deciding what to do about a finding — which range to standardise on,
whether an orphan should be declared or deleted — is the skill's
Analyze stage, not this script's.

Range admission for mono/internal-version-mismatch is checked for
exact pins and caret/tilde ranges only, by a simple semver compare;
`workspace:*`, `workspace:^`, and `*` always satisfy, and any other
range form is left unchecked (out of scope for this rule). Prints one
finding-list; a consistent workspace yields an empty `results` array
(SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a path that is not
a directory (repo-invalid) or a root or member manifest that does not
parse for its kind (manifest-unparseable).
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import tomllib
except ImportError:
    tomllib = None

LOCKFILES = ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb"]
ORPHAN_PARENTS = ["packages", "apps", "libs", "crates", "services"]
MANIFEST_FOR_KIND = {"npm": "package.json", "pnpm": "package.json", "cargo": "Cargo.toml",
                      "go": "go.mod", "uv": "pyproject.toml"}
ROOT_MANIFEST_FOR_KIND = {"npm": "package.json", "pnpm": "pnpm-workspace.yaml", "cargo": "Cargo.toml",
                           "go": "go.work", "uv": "pyproject.toml"}
VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}], "properties": props}


def fail(code, msg):
    sys.exit(f"ERROR: {msg} ({code})")


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        fail("manifest-unparseable", f"{path} cannot be read: {e}")


def load_json(path):
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as e:
        fail("manifest-unparseable", f"{path} is not valid JSON: {e}")


def minimal_toml_loads(text):
    """A hand-rolled reader for the flat TOML shapes this script needs
    -- string/bool scalars and string arrays under `[section]`/`[a.b]`
    headers -- used only when `tomllib` is unavailable (Python < 3.11,
    SDS-S-060 stdlib-only)."""
    root = {}
    node = root
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            node = root
            for key in line[1:-1].strip().split("."):
                node = node.setdefault(key.strip().strip("'\""), {})
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*=\s*(.+)$", line)
        if not m:
            continue
        key, raw_val = m.group(1).strip(), m.group(2).strip()
        if raw_val.startswith("[") and raw_val.endswith("]"):
            node[key] = [v.strip().strip("'\"") for v in
                         re.findall(r"\"[^\"]*\"|'[^']*'|[^,\[\]]+", raw_val[1:-1]) if v.strip()]
        elif raw_val in ("true", "false"):
            node[key] = raw_val == "true"
        else:
            node[key] = raw_val.strip("'\"")
    return root


def load_toml(path):
    text = read_text(path)
    if tomllib is not None:
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            fail("manifest-unparseable", f"{path} is not valid TOML: {e}")
    return minimal_toml_loads(text)


def toml_table(data, dotted):
    node = data
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, dict) else None


def load_pnpm_packages(path):
    """pnpm-workspace.yaml's `packages:` list -- a small hand parser
    over `- 'pattern'` lines, the shape actually used in practice."""
    patterns = []
    for line in read_text(path).splitlines():
        m = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*$", line)
        if m:
            patterns.append(m.group(1).strip())
    return patterns


def load_go_use(path):
    """go.work's `use (...)` block and standalone `use ./x` lines."""
    text = read_text(path)
    uses = []
    for block in re.findall(r"use\s*\(([^)]*)\)", text, re.DOTALL):
        for line in block.splitlines():
            line = line.strip()
            if line and not line.startswith("//"):
                uses.append(line)
    without_blocks = re.sub(r"use\s*\([^)]*\)", "", text)
    for m in re.finditer(r"^\s*use\s+(\S+)", without_blocks, re.MULTILINE):
        uses.append(m.group(1))
    return uses


def discover(root):
    """Detect the workspace kind in order (npm/yarn, pnpm, Cargo, Go,
    uv) and return (kind, declared-entries) -- (None, []) when nothing
    is recognised (SDS-C-033: not a failure)."""
    pkg_path = root / "package.json"
    if pkg_path.is_file():
        ws = load_json(pkg_path).get("workspaces")
        if ws is not None:
            return "npm", list(ws.get("packages") or []) if isinstance(ws, dict) else list(ws)

    pnpm_path = root / "pnpm-workspace.yaml"
    if pnpm_path.is_file():
        return "pnpm", load_pnpm_packages(pnpm_path)

    cargo_path = root / "Cargo.toml"
    if cargo_path.is_file():
        members = (toml_table(load_toml(cargo_path), "workspace") or {}).get("members")
        if members is not None:
            return "cargo", list(members)

    go_path = root / "go.work"
    if go_path.is_file():
        return "go", load_go_use(go_path)

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        members = (toml_table(load_toml(pyproject_path), "tool.uv.workspace") or {}).get("members")
        if members is not None:
            return "uv", list(members)

    return None, []


def expand_pattern(root, pattern):
    """Directories under root matching a declared entry -- a glob
    expansion for a pattern with wildcard characters, or the single
    directory named by a literal path -- regardless of whether a
    manifest is present."""
    p = pattern.rstrip("/")
    if any(ch in p for ch in "*?["):
        return [d for d in sorted(root.glob(p)) if d.is_dir()]
    d = root / p
    return [d] if d.is_dir() else []


def read_member(path, kind):
    """Return (name, version, deps) for one member manifest. `deps`
    maps a dependency name to its declared range string."""
    if kind in ("npm", "pnpm"):
        data = load_json(path)
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            for name, rng in (data.get(key) or {}).items():
                deps[name] = str(rng)
        return data.get("name"), str(data.get("version", "")), deps
    if kind == "cargo":
        data = load_toml(path)
        deps = {}
        for key in ("dependencies", "dev-dependencies", "build-dependencies"):
            for name, spec in (data.get(key) or {}).items():
                if isinstance(spec, dict):
                    if spec.get("workspace"):
                        deps[name] = "workspace:*"
                    elif spec.get("path") is not None:
                        deps[name] = f"path:{spec['path']}"
                    else:
                        deps[name] = str(spec.get("version", "*"))
                else:
                    deps[name] = str(spec)
        pkg = data.get("package") or {}
        return pkg.get("name"), str(pkg.get("version", "")), deps
    if kind == "go":
        m = re.search(r"^module\s+(\S+)", read_text(path), re.MULTILINE)
        return (m.group(1) if m else None), "", {}
    # uv
    data = load_toml(path)
    proj = data.get("project") or {}
    return proj.get("name"), str(proj.get("version", "")), {}


def sibling_satisfied(rng, version):
    """Does `rng` admit `version`? Only exact pins and caret/tilde
    ranges are checked, by a simple semver compare (SDS-S-060 keeps
    this mechanical); `workspace:*`, `workspace:^`, and `*` always
    satisfy, and any other range form is left unchecked."""
    rng = rng.strip()
    if rng in ("*", "") or rng.startswith("workspace:"):
        return True
    v = VER_RE.match(version)
    if not v:
        return True
    vt = tuple(int(x) for x in v.groups())
    m = re.match(r"^([\^~]?)(\d+)\.(\d+)\.(\d+)$", rng)
    if not m:
        return True
    op = m.group(1)
    parts = tuple(int(x) for x in m.groups()[1:])
    if op == "":
        return vt == parts
    if op == "^":
        if parts[0] > 0:
            return vt >= parts and vt[0] == parts[0]
        if parts[1] > 0:
            return vt >= parts and vt[0] == 0 and vt[1] == parts[1]
        return vt == parts
    if op == "~":
        return vt >= parts and vt[:2] == parts[:2]
    return True


def main():
    args = sys.argv[1:]
    if len(args) != 1:
        sys.exit("ERROR: usage: check_workspaces.py <repo-path>")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    kind, declared = discover(root)
    out = []
    all_members = []
    orphans = 0
    lockfiles_present = sorted(n for n in LOCKFILES if (root / n).is_file())

    if kind is not None:
        manifest_name = MANIFEST_FOR_KIND[kind]
        root_uri = ROOT_MANIFEST_FOR_KIND[kind]
        covered_dirs = set()
        by_dir = {}
        for pattern in declared:
            dirs = expand_pattern(root, pattern)
            found = False
            for d in dirs:
                rel = d.relative_to(root).as_posix()
                covered_dirs.add(rel)
                m = d / manifest_name
                if m.is_file():
                    found = True
                    if rel not in by_dir:
                        name, version, deps = read_member(m, kind)
                        uri = m.relative_to(root).as_posix()
                        by_dir[rel] = {"name": name or rel, "dir": rel, "uri": uri,
                                       "version": version, "deps": deps}
            if not found:
                out.append(finding("mono/member-missing", "error",
                                    f"declared workspace member {pattern!r} matches no directory with a "
                                    f"{manifest_name}",
                                    root_uri, {"pattern": pattern}))
        all_members = list(by_dir.values())

        for parent in ORPHAN_PARENTS:
            parent_dir = root / parent
            if not parent_dir.is_dir():
                continue
            for sub in sorted(parent_dir.iterdir()):
                if not sub.is_dir() or sub.relative_to(root).as_posix() in covered_dirs:
                    continue
                m = sub / manifest_name
                if not m.is_file():
                    continue
                rel = sub.relative_to(root).as_posix()
                uri = m.relative_to(root).as_posix()
                orphans += 1
                out.append(finding("mono/orphan-package", "warning",
                                    f"{rel} has a {manifest_name} but no workspace declaration covers it",
                                    uri, {"path": rel}))

        by_name = defaultdict(list)
        for mem in all_members:
            by_name[mem["name"]].append(mem)
        for name, mems in sorted(by_name.items()):
            if len(mems) > 1:
                paths = sorted(m["uri"] for m in mems)
                out.append(finding("mono/duplicate-name", "error",
                                    f"{len(mems)} workspace members share the name {name!r}: " +
                                    ", ".join(paths),
                                    paths[0], {"name": name, "paths": paths}))

        version_by_name = {}
        for mem in all_members:
            version_by_name.setdefault(mem["name"], mem["version"])
        for mem in sorted(all_members, key=lambda m: m["dir"]):
            for dep, rng in sorted(mem["deps"].items()):
                if dep in version_by_name:
                    actual = version_by_name[dep]
                    if not sibling_satisfied(rng, actual):
                        out.append(finding("mono/internal-version-mismatch", "warning",
                                            f"{mem['name']} depends on sibling {dep} at {rng!r} but "
                                            f"{dep} is {actual}",
                                            mem["uri"],
                                            {"from": mem["name"], "to": dep, "required": rng, "actual": actual}))

        if len(lockfiles_present) > 1:
            out.append(finding("mono/mixed-lockfiles", "warning",
                                f"more than one lockfile at the root: {', '.join(lockfiles_present)}",
                                lockfiles_present[0], {"lockfiles": lockfiles_present}))

        for mem in sorted(all_members, key=lambda m: m["dir"]):
            mem_dir = root / mem["dir"]
            for lf in LOCKFILES:
                if (mem_dir / lf).is_file():
                    uri = f"{mem['dir']}/{lf}"
                    out.append(finding("mono/nested-lockfile", "info",
                                        f"{mem['dir']} has its own {lf}",
                                        uri, {"path": uri}))

    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order[r["level"]], r["ruleId"],
                             r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]))

    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{
            "tool": {
                "driver": {"name": "workspace-consistency-check", "version": "0.1.0"},
                "properties": {
                    "kind": kind,
                    "members": len(all_members),
                    "declared": len(declared),
                    "orphans": orphans,
                    "lockfiles": lockfiles_present,
                },
            },
            "results": out,
        }],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
