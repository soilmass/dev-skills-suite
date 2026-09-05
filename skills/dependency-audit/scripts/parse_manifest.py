#!/usr/bin/env python3
"""Parse dependency manifests into a normalized list for OSV lookup.

Usage:
    parse_manifest.py <repo-path>

Prints a JSON array to stdout, one object per dependency:
    {"ecosystem": "npm"|"PyPI"|"crates.io", "name": str,
     "version": str|null, "resolved": bool, "source": str}

`resolved: true` means the version is a concrete pin (from a lockfile);
`resolved: false` means it's a declared range with the range operator
stripped (from the manifest itself, no lockfile present) and version
lookups against it are best-effort, not exact.

Exit code 0 with `[]` printed means: no manifest found, or a manifest
was found with zero dependencies. Per SDS-C-033 (Null Object
Requirement), this is a valid, complete result, not an error.

Exit code 1 means: a manifest was found but could not be parsed
(malformed JSON/TOML, or a required parser dependency is missing).
A one-line "ERROR: ..." message is printed to stderr identifying
exactly what failed, so the caller can fail fast with a specific
cause (SDS-C-019) rather than a generic message.
"""
import json
import re
import sys
from pathlib import Path


def _strip_range(spec):
    """Strip a leading npm/cargo range operator, return (version, resolved)."""
    if spec is None:
        return None, False
    stripped = re.sub(r"^[\^~>=<]+\s*", "", spec.strip())
    return (stripped or None), False


def parse_npm(repo):
    lockfile = repo / "package-lock.json"
    manifest = repo / "package.json"
    deps = []

    if lockfile.exists():
        try:
            data = json.loads(lockfile.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: package-lock.json is not valid JSON: {e}")
        packages = data.get("packages", {})
        for path, info in packages.items():
            if not path or path == "":
                continue  # the root package entry itself
            name = path.split("node_modules/")[-1]
            version = info.get("version")
            if name and version:
                deps.append({
                    "ecosystem": "npm", "name": name, "version": version,
                    "resolved": True, "source": "package-lock.json",
                })
        if deps:
            return deps
        # lockfile present but empty/unrecognized format: fall through
        # to package.json rather than silently returning nothing.

    if manifest.exists():
        try:
            data = json.loads(manifest.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: package.json is not valid JSON: {e}")
        for section in ("dependencies", "devDependencies"):
            for name, spec in data.get(section, {}).items():
                version, resolved = _strip_range(spec)
                deps.append({
                    "ecosystem": "npm", "name": name, "version": version,
                    "resolved": resolved, "source": "package.json",
                })
    return deps


def parse_pip(repo):
    reqs = repo / "requirements.txt"
    deps = []
    if not reqs.exists():
        return deps
    for lineno, raw in enumerate(reqs.read_text().splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(==)?\s*([A-Za-z0-9_.\-]*)$", line)
        if not m:
            continue
        name, exact_op, version = m.groups()
        deps.append({
            "ecosystem": "PyPI", "name": name,
            "version": version or None,
            "resolved": bool(exact_op and version),
            "source": f"requirements.txt:{lineno}",
        })
    return deps


def _load_toml(path):
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError:
            sys.exit(
                "ERROR: parsing Cargo.toml/Cargo.lock requires the 'tomli' "
                "package on Python < 3.11 (pip install tomli). Not installed."
            )
    try:
        return tomllib.loads(path.read_text())
    except Exception as e:  # tomllib/tomli raise their own TOMLDecodeError
        sys.exit(f"ERROR: {path.name} is not valid TOML: {e}")


def parse_cargo(repo):
    lockfile = repo / "Cargo.lock"
    manifest = repo / "Cargo.toml"
    deps = []

    if lockfile.exists():
        data = _load_toml(lockfile)
        for pkg in data.get("package", []):
            name, version = pkg.get("name"), pkg.get("version")
            if name and version:
                deps.append({
                    "ecosystem": "crates.io", "name": name, "version": version,
                    "resolved": True, "source": "Cargo.lock",
                })
        if deps:
            return deps

    if manifest.exists():
        data = _load_toml(manifest)
        for name, spec in data.get("dependencies", {}).items():
            spec_str = spec if isinstance(spec, str) else spec.get("version")
            version, resolved = _strip_range(spec_str)
            deps.append({
                "ecosystem": "crates.io", "name": name, "version": version,
                "resolved": resolved, "source": "Cargo.toml",
            })
    return deps


def main():
    if len(sys.argv) != 2:
        sys.exit("ERROR: usage: parse_manifest.py <repo-path>")
    repo = Path(sys.argv[1])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory: {repo}")

    deps = parse_npm(repo) + parse_pip(repo) + parse_cargo(repo)
    print(json.dumps(deps, indent=2))


if __name__ == "__main__":
    main()
