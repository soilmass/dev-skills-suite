#!/usr/bin/env python3
"""Generate the family's human-facing skill index from the registry.

Usage:
    render_index.py [--registry kit/registry/marketplace.json]
                    [--out README.md] [--check]

SDS-F-014: any human-facing index of the family's skills is generated
from kit/registry/marketplace.json, never hand-maintained. This script
is that generator. It writes a README at the family root containing a
table of every registered skill (name, kind derived from effect-tier,
tier, status, shapes, description) plus the fixed intro and usage text
below. With --check it exits 1 if the file on disk differs from what
it would generate — the CI guard against a hand-edited index.

Exit 1 with "ERROR: ..." on stderr if the registry cannot be read
(registry-unreadable) or, with --check, the index is stale.
"""
import json
import re
import sys
from pathlib import Path

RUNG = {
    "local-read-only": 1, "domain-read-only": 2, "external-read-only": 3,
    "local-write": 4, "shared-write": 5, "irreversible": 6,
}

HEADER = """# {family}

[![Conformance](https://github.com/soilmass/dev-skills-suite/actions/workflows/conformance.yml/badge.svg)](https://github.com/soilmass/dev-skills-suite/actions/workflows/conformance.yml)

A family of portable [Agent Skills](https://agentskills.io/specification)
for the software-development lifecycle, built to the Skill Design
Specification (SDS {sds}) in `docs/superpowers/specs/`.

Every skill is either a **Query Skill** (Effect Ladder rungs 1–3: reads,
never mutates; safe to run unattended) or a **Command Skill** (rungs 4–6:
performs an effect behind a confirmation gate, with a compensating action
and a two-phase checkpoint). Skills compose by agreeing on artifact
shapes (`kit/shapes/`), never by calling each other.

## Install

The family ships as one Claude Code plugin whose manifests
(`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) are
generated from the registry by `kit/scripts/render_plugin.py`:

```
/plugin marketplace add soilmass/dev-skills-suite
/plugin install dev-skills-suite@dev-skills-suite
```

Every skill is then available as `/dev-skills-suite:<skill>`. A
skill's commands are skill-relative (`scripts/<file>`, SDS-F-031) and
run from the skill's own directory — `${{CLAUDE_SKILL_DIR}}` once
installed — addressing any repository or external system explicitly
(SDS-S-056).

## Skills

_This table is generated from `kit/registry/marketplace.json` by
`kit/scripts/render_index.py` (SDS-F-014). Do not edit it by hand._

| Skill | Kind | Rung | Tier | Status | In → Out | What it does |
|---|---|---|---|---|---|---|
"""

FOOTER = """
## Using a skill

Each skill is a directory under `skills/` with a `SKILL.md` (the
instructions a model follows), `scripts/` for the mechanical parts,
optional `references/` and `assets/`, and `evals/` with a table-driven
eval file whose rows are real, runnable commands.

## Building a skill

Follow `kit/HOW-TO-BUILD-A-SKILL.md`, then run the conformance linter
and the eval runner:

    python3 kit/scripts/lint-skill.py skills/<name>
    python3 kit/scripts/lint-skill.py --all skills
    python3 kit/scripts/run-evals.py skills/<name>
    python3 kit/scripts/run-evals.py --all skills

A skill is done when the linter reports zero errors and every eval row
passes (SDS-S-110). The runner executes each row's command from the
skill directory and checks its exit code, failure code, and shape; the
prose assertions are read by a person.
"""


COMPOSITIONS = """
## Compositions

Skills compose by shape: any skill whose `shape-in` names a shape can
consume any skill whose `shape-out` is that shape (SDS-C-060). The
first table is the registry's shape graph; the list after it is every
contract pinned by a frozen recording or by running the consumer's own
script (SDS-C-063, SDS-S-093). Both are generated — see above.

| Shape | Produced by | Consumed by |
|---|---|---|
"""


def compositions(registry, root):
    """The shape graph from the registry and the pinned contracts from
    the eval tables and fixtures on disk."""
    names = {s["name"] for s in registry["skills"]}
    produced, consumed = {}, {}
    for s in registry["skills"]:
        produced.setdefault(s.get("shape-out", "freeform"), []).append(s["name"])
        for si in str(s.get("shape-in", "freeform")).split(","):
            consumed.setdefault(si.strip(), []).append(s["name"])
    shapes = sorted(set(produced) | set(consumed), key=lambda x: (x == "freeform", x))
    table = []
    for sh in shapes:
        p = ", ".join(f"`{n}`" for n in sorted(produced.get(sh, []))) or "—"
        c = ", ".join(f"`{n}`" for n in sorted(consumed.get(sh, []))) or "—"
        if sh == "freeform":
            p = f"{len(produced.get(sh, []))} skills (their `@returns` says what)"
            c = f"{len(consumed.get(sh, []))} skills (a repository, a file, a ref)"
        table.append(f"| `{sh}` | {p} | {c} |")
    by_len = sorted(names, key=len, reverse=True)

    def source_skill(stem):
        for k in by_len:
            if stem == k or stem.startswith(k + "-"):
                return k
        return None

    edges = set()
    for consumer in sorted(names):
        for f in sorted((root / "skills" / consumer / "evals" / "fixtures").glob("frozen-*")):
            producer = source_skill(f.name[len("frozen-"):].rsplit(".", 1)[0])
            if producer and producer != consumer:
                edges.add((producer, consumer, f"frozen recording `{f.name}`"))
        ev = root / "skills" / consumer / "evals" / f"{consumer}.eval.yaml"
        if ev.is_file():
            for other in set(re.findall(r"skills/([a-z0-9-]+)/scripts/", ev.read_text(encoding="utf-8"))):
                if other in names and other != consumer:
                    edges.add((consumer, other, f"`{consumer}`'s eval runs `{other}`'s script on the real output"))
    pinned = [f"- `{p}` → `{c}` — {how}" for p, c, how in sorted(edges)]
    return COMPOSITIONS + "\n".join(table) + "\n\n**Pinned contracts**\n\n" + "\n".join(pinned) + "\n"


def render(registry, root):
    rows = []
    for s in sorted(registry["skills"], key=lambda s: (RUNG[s["effect-tier"]], s["name"])):
        rung = RUNG[s["effect-tier"]]
        kind = "Query" if rung <= 3 else "Command"
        rows.append(
            f"| `{s['name']}` | {kind} | {rung} ({s['effect-tier']}) | {s['tier']} | {s.get('status', 'planned')} "
            f"| {s.get('shape-in', 'freeform')} → {s.get('shape-out', 'freeform')} | {s['description']} |"
        )
    return (HEADER.format(family=registry["family"], sds=registry.get("sds", "?")) + "\n".join(rows) + "\n"
            + compositions(registry, root) + FOOTER)


def main():
    args = sys.argv[1:]
    check = "--check" in args
    if check:
        args.remove("--check")
    def take(flag, default):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    root = Path(__file__).resolve().parent.parent.parent
    registry_path = Path(take("--registry", root / "kit" / "registry" / "marketplace.json"))
    out = Path(take("--out", root / "README.md"))
    if args:
        sys.exit("ERROR: usage: render_index.py [--registry <file>] [--out <file>] [--check]")
    try:
        registry = json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not read registry {registry_path} (registry-unreadable): {e}")

    text = render(registry, root)
    if check:
        current = out.read_text() if out.exists() else ""
        if current != text:
            sys.exit(f"ERROR: {out} is stale or hand-edited; regenerate with render_index.py")
        print(f"{out} is up to date")
        return
    out.write_text(text)
    print(f"wrote {out} ({len(registry['skills'])} skills)")


if __name__ == "__main__":
    main()
