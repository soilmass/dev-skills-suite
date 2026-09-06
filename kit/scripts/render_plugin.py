#!/usr/bin/env python3
"""Generate the Claude Code plugin and marketplace manifests from the
family registry (SDS-F-014 spirit: generated, never hand-edited).

Usage:
    render_plugin.py [--registry kit/registry/marketplace.json] [--check]

Writes, at the family root:
    .claude-plugin/plugin.json       the plugin: the family itself, with
                                     `skills` pointing at ./skills/ so
                                     every built skill ships as
                                     /<family>:<skill>
    .claude-plugin/marketplace.json  a one-plugin marketplace whose
                                     source is "./", so
                                     `/plugin marketplace add <owner>/<repo>`
                                     then `/plugin install <family>@<family>`
                                     installs the whole family

Only skills with `status: built` are described; the manifest's
`description` lists them by cluster-free name so the gallery shows what
is inside. `--check` exits 1 if either file differs from what would be
generated (run after any registry change, alongside render_index.py
--check). Exit 2 with "ERROR: ..." for an unreadable registry.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OWNER = {"name": "soilmass", "url": "https://github.com/soilmass"}
REPO_URL = "https://github.com/soilmass/dev-skills-suite"


def render(reg):
    built = [s for s in reg["skills"] if s.get("status") == "built"]
    names = ", ".join(s["name"] for s in built)
    desc = (f"{len(built)} software-development skills built to the Skill Design Specification (SDS {reg['sds']}): "
            f"{names}. Every skill declares its effect tier, ships its scripts and evals, and passes the family linter.")
    plugin = {
        "name": reg["family"],
        "displayName": "Dev Skills Suite",
        "version": reg["version"],
        "description": desc,
        "author": OWNER,
        "homepage": REPO_URL,
        "repository": REPO_URL,
        "license": "Apache-2.0",
        "keywords": ["skills", "software-development", "github", "code-quality", "testing", "ci", "documentation", "observability", "sds"],
        "skills": "./skills/",
    }
    marketplace = {
        "name": reg["family"],
        "description": "The dev-skills-suite family: one plugin bundling every built skill.",
        "owner": OWNER,
        "plugins": [{
            "name": reg["family"],
            "source": "./",
            "description": f"{len(built)} SDS-conformant skills for software development; install once, invoke as /{reg['family']}:<skill>.",
            "version": reg["version"],
            "author": OWNER,
            "homepage": REPO_URL,
            "repository": REPO_URL,
            "license": "Apache-2.0",
            "category": "development",
            "keywords": plugin["keywords"],
            "tags": sorted({s["effect-tier"] for s in built}),
        }],
    }
    return plugin, marketplace


def main():
    args = sys.argv[1:]
    check = "--check" in args
    reg_path = ROOT / "kit/registry/marketplace.json"
    if "--registry" in args:
        reg_path = Path(args[args.index("--registry") + 1])
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        assert "version" in reg, "registry lacks a top-level version"
    except (OSError, json.JSONDecodeError, AssertionError) as e:
        sys.exit(f"ERROR: could not load registry {reg_path}: {e}")
    plugin, marketplace = render(reg)
    out = {ROOT / ".claude-plugin/plugin.json": plugin, ROOT / ".claude-plugin/marketplace.json": marketplace}
    stale = []
    for path, doc in out.items():
        text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if check:
        if stale:
            sys.exit("ERROR: stale, regenerate with render_plugin.py: " + ", ".join(stale))
        print("plugin manifests are up to date")


if __name__ == "__main__":
    main()
