#!/usr/bin/env python3
"""Check a migration plan-doc for the parallel-change discipline and
render it as a phased checklist.

Usage:
    check_migration_plan.py <plan.json> [--render]

Validates against kit/shapes/plan-doc.schema.json, then enforces the
one structural rule of a safe migration — the expand/migrate/contract
sequence (parallel change; the Strangler Fig adoption rule this family
already applies to itself, SDS-C-062):

    1. phases MUST be, in order, one whose name starts with "Expand",
       one or more starting with "Migrate", then one starting with
       "Contract"; a plan with no Expand phase, or with Contract before
       the last Migrate, is refused (plan-not-parallel-change);
    2. every step in the Expand and Migrate phases MUST have a real
       rollback (not "none") — until contraction nothing is
       irreversible (plan-not-parallel-change);
    3. the Contract phase MUST begin with a step whose description
       contains "verify" — the old path is removed only after proof
       that nothing uses it (plan-not-parallel-change);
    4. a Contract step with rollback "none" MUST be last in the phase
       (plan-unsafe-order — the same saga rule rollback-plan-writer
       enforces).

Warnings (never failures; whether they matter is the skill's Analyze
stage): a Migrate phase with a single step (the slice is probably too
big to ship independently); a plan whose goal does not name both the
old and the new path ("from X to Y").

Prints {"plan", "warnings", "phases": {"expand": n, "migrate": n,
"contract": n}, "rendered"?}. Exit 1 with "ERROR: ..." on stderr for
an unreadable/malformed input (plan-unparseable), a plan failing the
shape (plan-invalid), or the rule violations above. Requires the
`jsonschema` package.
"""
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")


def family_root(start):
    for c in [start, *start.parents]:
        if (c / "kit").is_dir():
            return c
    return None


def kind(phase):
    n = phase["name"].strip().lower()
    for k in ("expand", "migrate", "contract"):
        if n.startswith(k):
            return k
    return None


def irreversible(step):
    return step["rollback"].strip().lower().startswith("none")


def check(plan):
    kinds = [kind(p) for p in plan["phases"]]
    if None in kinds:
        bad = plan["phases"][kinds.index(None)]["name"]
        sys.exit(f"ERROR: phase {bad!r} is not an Expand, Migrate, or Contract phase (plan-not-parallel-change)")
    if kinds.count("expand") != 1 or kinds.count("contract") != 1 or "migrate" not in kinds:
        sys.exit("ERROR: a migration plan needs exactly one Expand phase, one or more Migrate phases, and one Contract phase (plan-not-parallel-change)")
    if kinds[0] != "expand" or kinds[-1] != "contract" or any(k == "contract" for k in kinds[:-1]):
        sys.exit("ERROR: phases must run Expand -> Migrate... -> Contract; Contract must be last (plan-not-parallel-change)")
    warnings = []
    for phase, k in zip(plan["phases"], kinds):
        steps = phase["steps"]
        if k in ("expand", "migrate"):
            for s in steps:
                if irreversible(s):
                    sys.exit(f"ERROR: {phase['name']!r} step {s['description']!r} has no rollback; nothing may be irreversible before Contract (plan-not-parallel-change)")
            if k == "migrate" and len(steps) == 1:
                warnings.append(f"{phase['name']}: a single-step migrate phase is rarely an independently shippable slice")
        else:
            if not steps or "verify" not in steps[0]["description"].lower():
                sys.exit("ERROR: the Contract phase must begin with a verification step (description containing 'verify') before removing the old path (plan-not-parallel-change)")
            for i, s in enumerate(steps):
                if irreversible(s) and i != len(steps) - 1:
                    sys.exit(f"ERROR: Contract step {s['description']!r} has no rollback but is not last in its phase (plan-unsafe-order)")
    if not re.search(r"\bfrom\b.+\bto\b", plan["goal"], re.I):
        warnings.append("goal does not name both the old and the new path ('from X to Y')")
    return warnings, {k: kinds.count(k) for k in ("expand", "migrate", "contract")}


def render(plan):
    lines = [f"# Migration plan: {plan['goal']}", ""]
    for phase in plan["phases"]:
        lines += [f"## {phase['name']}", ""]
        for s in phase["steps"]:
            mark = " **(irreversible — last)**" if irreversible(s) else ""
            lines += [f"- [ ] {s['description']} _(risk if fails: {s['riskIfFails']})_{mark}", f"      rollback: {s['rollback']}"]
        lines.append("")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    do_render = "--render" in args
    if do_render:
        args.remove("--render")
    if len(args) != 1:
        sys.exit("ERROR: usage: check_migration_plan.py <plan.json> [--render]")
    try:
        plan = json.loads(Path(args[0]).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load plan {args[0]} (plan-unparseable): {e}")
    root = family_root(Path(__file__).resolve())
    if root is None:
        sys.exit("ERROR: could not locate the family root (a directory containing kit/) above this script")
    try:
        jsonschema.validate(plan, json.loads((root / "kit/shapes/plan-doc.schema.json").read_text()))
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: plan fails kit/shapes/plan-doc.schema.json (plan-invalid): {e.message}")
    warnings, counts = check(plan)
    out = {"plan": plan, "warnings": warnings, "phases": counts}
    if do_render:
        out["rendered"] = render(plan)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
