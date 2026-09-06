#!/usr/bin/env python3
"""Check the component licenses in a CycloneDX BOM against the
repository's own license and emit a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    check_licenses.py --bom <bom.json> --own-license <SPDX-id>
                      [--allow <id,id,...>] [--deny <id,id,...>]

Licenses are SPDX identifiers and expressions (SDS-C-031, standards
first). Each component's `licenses[].expression` (or `.license.id`) is
evaluated; `A OR B` passes if any alternative passes, `A AND B` only if
all do. Categories (see references/license-categories.md):
    permissive       MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC,
                     0BSD, Unlicense, WTFPL, CC0-1.0, Zlib, PSF-2.0,
                     BlueOak-1.0.0, MIT-0, BSL-1.0
    weak-copyleft    LGPL-2.1-only/-or-later, LGPL-3.0-only/-or-later,
                     MPL-2.0, EPL-1.0, EPL-2.0, CDDL-1.0
    strong-copyleft  GPL-2.0-only/-or-later, GPL-3.0-only/-or-later
    network-copyleft AGPL-3.0-only/-or-later, SSPL-1.0
    unknown          anything else, or no license declared

Policy (deterministic; whether a breach is acceptable in context —
dynamic linking, an internal tool never distributed — is the skill's
Analyze stage, never this script's):
    project permissive or proprietary:
        strong/network copyleft -> license/incompatible  (error)
        weak copyleft           -> license/review        (warning)
    project weak copyleft:
        strong/network copyleft -> license/incompatible  (error)
    project strong copyleft (GPL):
        network copyleft (AGPL) -> license/review        (warning)
    any project:
        unknown / undeclared    -> license/unknown       (warning)
        deprecated SPDX id (e.g. "GPL-3.0", "LGPL-2.1", "GPL-2.0")
                                -> license/nonstandard-id (info),
                                   evaluated as its -only form
        --deny list             -> license/incompatible  (error)
        --allow list            -> passes, with a
                                   license/allowlisted   (info) note

Prints one finding-list; a BOM whose components all pass yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for an unreadable/malformed BOM (bom-unparseable), a BOM lacking
bomFormat/components (bom-invalid), or an unrecognized project
license category (bad-argument).
"""
import json
import re
import sys
from pathlib import Path

CATEGORIES = {
    "permissive": {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "0BSD", "Unlicense", "WTFPL",
                   "CC0-1.0", "Zlib", "PSF-2.0", "BlueOak-1.0.0", "MIT-0", "BSL-1.0"},
    "weak-copyleft": {"LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later", "MPL-2.0",
                      "EPL-1.0", "EPL-2.0", "CDDL-1.0"},
    "strong-copyleft": {"GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later"},
    "network-copyleft": {"AGPL-3.0-only", "AGPL-3.0-or-later", "SSPL-1.0"},
}
DEPRECATED = {"GPL-2.0": "GPL-2.0-only", "GPL-2.0+": "GPL-2.0-or-later", "GPL-3.0": "GPL-3.0-only",
              "GPL-3.0+": "GPL-3.0-or-later", "LGPL-2.1": "LGPL-2.1-only", "LGPL-2.1+": "LGPL-2.1-or-later",
              "LGPL-3.0": "LGPL-3.0-only", "AGPL-3.0": "AGPL-3.0-only"}
RANK = {"permissive": 0, "weak-copyleft": 1, "strong-copyleft": 2, "network-copyleft": 3}


def category(license_id):
    for cat, ids in CATEGORIES.items():
        if license_id in ids:
            return cat
    return "unknown"


def normalize(license_id):
    return DEPRECATED.get(license_id, license_id), license_id in DEPRECATED


def project_category(license_id):
    if license_id.lower() in ("proprietary", "unlicensed", "closed"):
        return "proprietary"
    cat = category(normalize(license_id)[0])
    if cat == "unknown":
        sys.exit(f"ERROR: project license {license_id!r} is not a recognized SPDX identifier in this policy (bad-argument)")
    return cat


def evaluate(license_id, project_cat, allow, deny):
    """Return (rule, level, note) for one atomic license id, or None if it passes."""
    lid, deprecated = normalize(license_id)
    if lid in deny:
        return "license/incompatible", "error", f"{license_id} is on the deny list"
    if lid in allow:
        return "license/allowlisted", "info", f"{license_id} passes only because it is on the allow list"
    cat = category(lid)
    if cat == "unknown":
        return "license/unknown", "warning", f"{license_id} is not a recognized SPDX identifier"
    pr = RANK.get(project_cat, 0) if project_cat != "proprietary" else 0
    if cat in ("strong-copyleft", "network-copyleft") and pr < RANK["strong-copyleft"]:
        return "license/incompatible", "error", f"{license_id} ({cat}) cannot be combined with a {project_cat} codebase"
    if cat == "network-copyleft" and pr == RANK["strong-copyleft"]:
        return "license/review", "warning", f"{license_id} adds network-use obligations beyond the project's GPL"
    if cat == "weak-copyleft" and pr < RANK["weak-copyleft"]:
        return "license/review", "warning", f"{license_id} ({cat}) is acceptable only under its linking/modification terms"
    return None


def evaluate_expression(expr, project_cat, allow, deny):
    """OR: pass if any alternative passes (report the best); AND: report every failing part."""
    expr = expr.strip().strip("()")
    if " OR " in expr:
        outcomes = [evaluate_expression(p, project_cat, allow, deny) for p in expr.split(" OR ")]
        if any(o is None for o in outcomes):
            return None
        return min(outcomes, key=lambda o: {"error": 2, "warning": 1, "info": 0}[o[1]])
    if " AND " in expr:
        outcomes = [evaluate_expression(p, project_cat, allow, deny) for p in expr.split(" AND ")]
        failing = [o for o in outcomes if o is not None]
        return max(failing, key=lambda o: {"error": 2, "warning": 1, "info": 0}[o[1]]) if failing else None
    return evaluate(expr, project_cat, allow, deny)


def finding(rule, level, text, comp, extra):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": comp.get("purl") or comp["name"]}}}],
            "properties": {"component": comp["name"], "version": comp.get("version"), **extra}}


def main():
    args = sys.argv[1:]
    def take(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value (bad-argument)")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None
    bom_path, project_license = take("--bom"), take("--own-license")
    allow = {x.strip() for x in (take("--allow") or "").split(",") if x.strip()}
    deny = {x.strip() for x in (take("--deny") or "").split(",") if x.strip()}
    if args or not bom_path or not project_license:
        sys.exit("ERROR: usage: check_licenses.py --bom <bom.json> --own-license <SPDX-id> [--allow ids] [--deny ids]")
    try:
        bom = json.loads(Path(bom_path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load BOM {bom_path} (bom-unparseable): {e}")
    if not isinstance(bom, dict) or bom.get("bomFormat") != "CycloneDX" or not isinstance(bom.get("components"), list):
        sys.exit(f"ERROR: {bom_path} is not a CycloneDX BOM with a components array (bom-invalid)")
    project_cat = project_category(project_license)

    results = []
    for comp in bom["components"]:
        exprs = []
        for lic in comp.get("licenses") or []:
            if isinstance(lic, dict):
                exprs.append(lic.get("expression") or (lic.get("license") or {}).get("id") or (lic.get("license") or {}).get("name"))
        exprs = [e for e in exprs if e]
        if not exprs:
            results.append(finding("license/unknown", "warning", f"{comp['name']}@{comp.get('version')} declares no license", comp,
                                   {"license": None, "projectLicense": project_license}))
            continue
        for expr in exprs:
            for atom in re.split(r"\s+(?:OR|AND)\s+", expr.strip("()")):
                if atom in DEPRECATED:
                    results.append(finding("license/nonstandard-id", "info",
                                           f"{comp['name']} uses deprecated SPDX id {atom!r}; evaluated as {DEPRECATED[atom]!r}", comp,
                                           {"license": atom, "evaluatedAs": DEPRECATED[atom]}))
            outcome = evaluate_expression(expr, project_cat, allow, deny)
            if outcome:
                rule, level, note = outcome
                results.append(finding(rule, level, f"{comp['name']}@{comp.get('version')}: {note}", comp,
                                       {"license": expr, "projectLicense": project_license, "projectCategory": project_cat}))
    order = {"error": 0, "warning": 1, "info": 2}
    results.sort(key=lambda r: (order[r["level"]], r["properties"]["component"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "license-compliance-check", "version": "0.1.0"}}, "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
