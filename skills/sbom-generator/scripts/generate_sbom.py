#!/usr/bin/env python3
"""Generate a CycloneDX software bill of materials from a project's
manifests and lockfiles.

Usage:
    generate_sbom.py <project-dir> [--name <project-name>]
                     [--version <project-version>]
                     [--timestamp <ISO-8601>] [--serial <urn:uuid:...>]

Output convention is CycloneDX 1.5 JSON (SDS-C-031, standards first:
ECMA-424 / OWASP CycloneDX). Components are read from, in order of
preference per ecosystem:
    npm        package-lock.json (v2/v3 `packages`), else package.json
               declared ranges (range operator stripped, scope
               "declared-range" noted in properties)
    PyPI       requirements.txt exact pins only (name==version)
    crates.io  Cargo.lock [[package]], else Cargo.toml [dependencies]
Each component carries a purl (pkg:npm/<name>@<version>,
pkg:pypi/<name>@<version>, pkg:cargo/<name>@<version>). Licenses are
taken only from where a manifest actually declares them —
node_modules/<name>/package.json `license` for npm — and are emitted
as SPDX expressions; a component with no discoverable license carries
no `licenses` key at all rather than a guess.

Hermetic by design (SDS-C-003): CycloneDX's `metadata.timestamp` and
`serialNumber` are omitted unless passed explicitly, so the same tree
always produces the same document byte for byte. Effect Ladder rung 1.

Prints one CycloneDX JSON document. A project with no manifests
yields a valid BOM with an empty `components` array (SDS-C-033). Exit
1 with "ERROR: ..." on stderr for a path that is not a directory
(project-invalid) or a manifest that exists but does not parse
(manifest-unparseable). Cargo files on Python < 3.11 need `tomli`
(dependency-missing).
"""
import json
import re
import sys
from pathlib import Path


def strip_range(spec):
    return re.sub(r"^[\^~>=<]+\s*", "", (spec or "").strip()) or None


def load_toml(path):
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError:
            sys.exit("ERROR: parsing Cargo files needs 'tomli' on Python < 3.11 (dependency-missing)")
    try:
        return tomllib.loads(path.read_text())
    except Exception as e:
        sys.exit(f"ERROR: {path.name} is not valid TOML (manifest-unparseable): {e}")


def load_json(path):
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {path.name} is not valid JSON (manifest-unparseable): {e}")


def npm_license(project, name):
    meta = project / "node_modules" / name / "package.json"
    if not meta.is_file():
        return None
    try:
        lic = json.loads(meta.read_text()).get("license")
    except json.JSONDecodeError:
        return None
    if isinstance(lic, dict):
        lic = lic.get("type")
    return lic if isinstance(lic, str) and lic.strip() else None


def component(ecosystem, purl_type, name, version, project, declared_range=False):
    comp = {"type": "library", "name": name, "version": version,
            "purl": f"pkg:{purl_type}/{name}@{version}",
            "properties": [{"name": "sds:ecosystem", "value": ecosystem}]}
    if declared_range:
        comp["properties"].append({"name": "sds:version-source", "value": "declared-range"})
    if ecosystem == "npm":
        lic = npm_license(project, name)
        if lic:
            comp["licenses"] = [{"expression": lic}]
    return comp


def collect(project):
    comps = []
    lock, manifest = project / "package-lock.json", project / "package.json"
    if lock.is_file():
        for path, info in load_json(lock).get("packages", {}).items():
            if not path:
                continue
            name = path.split("node_modules/")[-1]
            if info.get("version"):
                comps.append(component("npm", "npm", name, info["version"], project))
    elif manifest.is_file():
        data = load_json(manifest)
        for section in ("dependencies", "devDependencies"):
            for name, spec in data.get(section, {}).items():
                v = strip_range(spec)
                if v:
                    comps.append(component("npm", "npm", name, v, project, declared_range=True))
    reqs = project / "requirements.txt"
    if reqs.is_file():
        for line in reqs.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            m = re.match(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-]+)$", line)
            if m:
                comps.append(component("PyPI", "pypi", m.group(1).lower(), m.group(2), project))
    clock, cmanifest = project / "Cargo.lock", project / "Cargo.toml"
    if clock.is_file():
        for pkg in load_toml(clock).get("package", []):
            # Cargo.lock lists the workspace's own crates too; they have no
            # `source` (path packages) and are not dependencies.
            if pkg.get("name") and pkg.get("version") and pkg.get("source"):
                comps.append(component("crates.io", "cargo", pkg["name"], pkg["version"], project))
    elif cmanifest.is_file():
        for name, spec in load_toml(cmanifest).get("dependencies", {}).items():
            v = strip_range(spec if isinstance(spec, str) else spec.get("version"))
            if v:
                comps.append(component("crates.io", "cargo", name, v, project, declared_range=True))
    return sorted(comps, key=lambda c: c["purl"])


def main():
    args = sys.argv[1:]
    def take(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None
    name, version, timestamp, serial = take("--name"), take("--version"), take("--timestamp"), take("--serial")
    if len(args) != 1:
        sys.exit("ERROR: usage: generate_sbom.py <project-dir> [--name N] [--version V] [--timestamp T] [--serial URN]")
    project = Path(args[0])
    if not project.is_dir():
        sys.exit(f"ERROR: not a directory (project-invalid): {project}")

    bom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
           "metadata": {"tools": [{"vendor": "dev-skills-suite", "name": "sbom-generator", "version": "0.1.0"}]},
           "components": collect(project)}
    if serial:
        bom["serialNumber"] = serial
    if timestamp:
        bom["metadata"]["timestamp"] = timestamp
    if name:
        bom["metadata"]["component"] = {"type": "application", "name": name, **({"version": version} if version else {})}
    print(json.dumps(bom, indent=2))


if __name__ == "__main__":
    main()
