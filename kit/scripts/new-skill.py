#!/usr/bin/env python3
"""Scaffold a new Skill package from the family's templates (SDS 1.0-draft).

Usage:
    new-skill.py <name> --kind query|command --rung 1..6
                 --shape-out <shape|freeform> [--shape-in <shape|freeform>]
                 [--script <snake_name>.py] [--kit <kit-dir>]

Creates skills/<name>/{SKILL.md, scripts/<script>, evals/<name>.eval.yaml,
evals/fixtures/.gitkeep} from kit/templates/SKILL.md.<kind>.template and
kit/evals/TEMPLATE.eval.yaml, and appends a `status: "planned"` entry to
kit/registry/marketplace.json. Only the mechanical fields are filled in —
name, family (read from the registry's `family` field), effect-tier (from
--rung), shape-out, shape-in, and allowed-tools. Every other bracketed
prose marker (`[FILL ...]`, `[Write this LAST ...]`, etc.) is left in
place on purpose: kit/scripts/lint-skill.py's residue rule (SDS-S-033) is
the reminder for the author to finish them.

Rung -> effect-tier: 1 local-read-only, 2 domain-read-only,
3 external-read-only, 4 local-write, 5 shared-write, 6 irreversible.
Rungs 1-3 are Query Skills (kind=query); 4-6 are Command Skills
(kind=command); --kind must agree with --rung.

Exit 2 with "ERROR: ..." on stderr on failure (bad-name, kind/rung
mismatch, unregistered shape, skills/<name>/ already exists, or a
registry entry named <name> already exists) — nothing is written in
that case. On success, prints each created path, one per line.

Family root = parent of --kit (default: two levels above this file, i.e.
the kit/ directory itself). Never the git toplevel.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

RUNG_EFFECT_TIER = {
    1: "local-read-only",
    2: "domain-read-only",
    3: "external-read-only",
    4: "local-write",
    5: "shared-write",
    6: "irreversible",
}
RUNG_KIND = {1: "query", 2: "query", 3: "query", 4: "command", 5: "command", 6: "command"}


def fail(msg: str) -> None:
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.exit(2)


def registered_shapes(kit_dir: Path) -> set[str]:
    return {p.name[: -len(".schema.json")] for p in (kit_dir / "shapes").glob("*.schema.json")}


def sub_scalar(text: str, field: str, new_value: str) -> str:
    """Replace metadata.<field>'s value in a frontmatter block, whether it
    is given as a bracket enumeration (`field: [a | b | c]`) or a bare
    value with an optional trailing comment (`field: value   # comment`).
    A trailing comment, if present, is preserved untouched."""
    bracket_re = re.compile(rf"(?m)^(\s*{re.escape(field)}:\s*)\[[^\]]*\]")
    if bracket_re.search(text):
        return bracket_re.sub(lambda m: m.group(1) + new_value, text, count=1)
    value_re = re.compile(rf"(?m)^(\s*{re.escape(field)}:\s*)(\S+)")
    return value_re.sub(lambda m: m.group(1) + new_value, text, count=1)


def sub_allowed_tools(fm_text: str, script_name: str) -> str:
    """Set metadata's allowed-tools to the one bundled script plus Read,
    replacing an existing (placeholder) allowed-tools block if the
    template has one, or appending a new key if it doesn't."""
    new_block = f"allowed-tools: >-\n  Bash(python3 scripts/{script_name}:*) Read"
    existing_re = re.compile(r"(?m)^allowed-tools:.*\n(?:[ \t]+.*\n?)*")
    if existing_re.search(fm_text):
        return existing_re.sub(new_block + "\n", fm_text, count=1)
    return fm_text.rstrip("\n") + "\n" + new_block


def render_skill_md(
    template_text: str,
    *,
    name: str,
    family: str,
    effect_tier: str,
    shape_out: str,
    shape_in: str | None,
    script_name: str,
) -> str:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", template_text, re.DOTALL)
    if not m:
        fail("template is not well-formed (missing frontmatter delimiters)")
    fm_text, body = m.group(1), m.group(2)

    fm_text = sub_scalar(fm_text, "name", name)
    fm_text = sub_scalar(fm_text, "family", family)
    fm_text = sub_scalar(fm_text, "effect-tier", effect_tier)
    fm_text = sub_scalar(fm_text, "shape-out", shape_out)
    if shape_in is not None:
        fm_text = sub_scalar(fm_text, "shape-in", shape_in)
    fm_text = sub_allowed_tools(fm_text, script_name).rstrip("\n")

    text = f"---\n{fm_text}\n---\n{body}"
    text = text.replace("# [Skill Name]", f"# {name}", 1)
    return text


def render_eval_yaml(template_text: str, name: str) -> str:
    return template_text.replace("<skill-name>", name)


def render_script(name: str, failure_code_hint: str) -> str:
    return f'''#!/usr/bin/env python3
"""Deterministic helper for the {name} skill.

Usage:
    {name.replace("-", "_")}.py [args]

Prints a single JSON object to stdout on success. Exit 1 with
"ERROR: ... ({failure_code_hint})" on stderr on failure.
"""
import sys


def main() -> int:
    print("{{}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def build_registry_entry(name: str, effect_tier: str, shape_out: str, shape_in: str) -> dict:
    return {
        "name": name,
        "description": "[FILL: description]",
        "version": "0.1.0",
        "effect-tier": effect_tier,
        "tier": "situational",
        "shape-out": shape_out,
        "shape-in": shape_in,
        "status": "planned",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="new-skill.py",
        description="Scaffold a new Skill package from the family's templates.",
    )
    ap.add_argument("name", help="skill name, e.g. my-new-skill")
    ap.add_argument("--kind", required=True, choices=["query", "command"])
    ap.add_argument("--rung", required=True, type=int, choices=range(1, 7), metavar="1..6")
    ap.add_argument("--shape-out", required=True, help="a kit/shapes/*.schema.json name, or freeform")
    ap.add_argument("--shape-in", default=None, help="a kit/shapes/*.schema.json name, or freeform")
    ap.add_argument("--script", default=None, help="scripts/<name> stub filename (default: <name with -> _>.py)")
    ap.add_argument("--kit", default=None, help="kit directory (default: two levels above this file)")
    args = ap.parse_args(argv)

    kit_dir = Path(args.kit).resolve() if args.kit else Path(__file__).resolve().parent.parent
    family_root = kit_dir.parent
    skills_dir = family_root / "skills"
    registry_path = kit_dir / "registry" / "marketplace.json"

    if not NAME_RE.match(args.name):
        fail(f"name {args.name!r} does not match ^[a-z0-9]+(-[a-z0-9]+)*$")

    expected_kind = RUNG_KIND[args.rung]
    if args.kind != expected_kind:
        fail(
            f"--kind {args.kind!r} disagrees with --rung {args.rung} "
            f"(rung {args.rung} is a {expected_kind} skill; rungs 1-3 are query, 4-6 are command)"
        )

    shapes = registered_shapes(kit_dir)
    allowed_shapes = shapes | {"freeform"}
    if args.shape_out not in allowed_shapes:
        fail(f"--shape-out {args.shape_out!r} is not one of {sorted(allowed_shapes)}")
    if args.shape_in is not None and args.shape_in not in allowed_shapes:
        fail(f"--shape-in {args.shape_in!r} is not one of {sorted(allowed_shapes)}")

    skill_dir = skills_dir / args.name
    if skill_dir.exists():
        fail(f"{skill_dir} already exists")

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        fail(f"cannot read registry {registry_path}: {e}")
    family = registry.get("family")
    if not family:
        fail(f"registry {registry_path} has no top-level 'family' field")
    if any(isinstance(e, dict) and e.get("name") == args.name for e in registry.get("skills", [])):
        fail(f"a registry entry named {args.name!r} already exists in {registry_path}")

    template_path = kit_dir / "templates" / f"SKILL.md.{args.kind}.template"
    try:
        template_text = template_path.read_text(encoding="utf-8")
    except OSError as e:
        fail(f"cannot read template {template_path}: {e}")

    eval_template_path = kit_dir / "evals" / "TEMPLATE.eval.yaml"
    try:
        eval_template_text = eval_template_path.read_text(encoding="utf-8")
    except OSError as e:
        fail(f"cannot read eval template {eval_template_path}: {e}")

    effect_tier = RUNG_EFFECT_TIER[args.rung]
    script_name = args.script or f"{args.name.replace('-', '_')}.py"
    # For a command template, an unfilled shape-in bracket would leave the
    # frontmatter value as a YAML list rather than a scalar; default it to
    # freeform (the same fallback the query template's shape-in already
    # carries verbatim) when the caller didn't pass one.
    shape_in = args.shape_in if args.shape_in is not None else ("freeform" if args.kind == "command" else None)

    skill_md = render_skill_md(
        template_text,
        name=args.name,
        family=family,
        effect_tier=effect_tier,
        shape_out=args.shape_out,
        shape_in=shape_in,
        script_name=script_name,
    )
    eval_yaml = render_eval_yaml(eval_template_text, args.name)
    script_body = render_script(args.name, "failure-code")

    # Everything validated — now write.
    created: list[Path] = []

    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "evals" / "fixtures").mkdir(parents=True)

    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(skill_md, encoding="utf-8")
    created.append(skill_md_path)

    script_path = skill_dir / "scripts" / script_name
    script_path.write_text(script_body, encoding="utf-8")
    script_path.chmod(script_path.stat().st_mode | 0o111)
    created.append(script_path)

    eval_path = skill_dir / "evals" / f"{args.name}.eval.yaml"
    eval_path.write_text(eval_yaml, encoding="utf-8")
    created.append(eval_path)

    gitkeep_path = skill_dir / "evals" / "fixtures" / ".gitkeep"
    gitkeep_path.write_text("", encoding="utf-8")
    created.append(gitkeep_path)

    registry.setdefault("skills", []).append(
        build_registry_entry(args.name, effect_tier, args.shape_out, shape_in if shape_in is not None else "freeform")
    )
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    created.append(registry_path)

    for p in created:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
