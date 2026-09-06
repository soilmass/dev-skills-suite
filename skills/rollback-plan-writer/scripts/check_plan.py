#!/usr/bin/env python3
"""Check a rollback plan-doc for structural safety and render it as a
checklist.

Usage:
    check_plan.py <plan.json> [--render]

Validates the plan against kit/shapes/plan-doc.schema.json, then
applies the one ordering rule a rollback plan must satisfy and that no
schema can express: within a phase, a step whose rollback is "none"
(irreversible) MUST be the last step of that phase — nothing may be
sequenced after a step that cannot be undone, because rolling the
phase back would stop there with later steps stranded (SDS-C-045,
sagas). A plan that violates it is refused (plan-unsafe-order); the
message names the offending step.

Also reports, as warnings (never failures — whether they matter is the
skill's Analyze stage):
    - a step at riskIfFails "high" whose rollback is "none"
    - a phase with no steps marked checkpointAfter
    - a rollback text shorter than 12 characters ("revert", "undo")

With --render, prints a markdown checklist alongside: one `- [ ]` per
step with its rollback indented beneath, phases as headings, the
irreversible steps marked.

Prints {"plan": <input>, "warnings": [...], "irreversible": [...],
"rendered"?}. Exit 1 with "ERROR: ..." on stderr for an unreadable or
malformed input (plan-unparseable), a plan failing the shape
(plan-invalid), or an unsafe ordering (plan-unsafe-order). Requires
the `jsonschema` package.
"""
import json
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


def is_irreversible(step):
    return step["rollback"].strip().lower().startswith("none")


def check(plan):
    warnings, irreversible = [], []
    for phase in plan["phases"]:
        steps = phase["steps"]
        for idx, step in enumerate(steps):
            if is_irreversible(step):
                irreversible.append(f"{phase['name']}: {step['description']}")
                if idx != len(steps) - 1:
                    sys.exit(
                        f"ERROR: phase {phase['name']!r} step {idx + 1} ({step['description']!r}) has no rollback "
                        f"but is followed by {len(steps) - idx - 1} more step(s); an irreversible step must be last "
                        f"in its phase (plan-unsafe-order)"
                    )
                if step["riskIfFails"] == "high":
                    warnings.append(f"{phase['name']}: {step['description']!r} is high-risk with no rollback")
            if len(step["rollback"].strip()) < 12 and not is_irreversible(step):
                warnings.append(f"{phase['name']}: rollback for {step['description']!r} is too terse to execute: {step['rollback']!r}")
        if steps and not any(s.get("checkpointAfter", True) for s in steps):
            warnings.append(f"{phase['name']}: no step is checkpointed; a resumed run cannot tell where it stopped")
    return warnings, irreversible


def render(plan):
    lines = [f"# Rollback plan: {plan['goal']}", ""]
    for phase in plan["phases"]:
        lines += [f"## {phase['name']}", ""]
        for step in phase["steps"]:
            mark = " **(irreversible — last in phase)**" if is_irreversible(step) else ""
            lines += [f"- [ ] {step['description']} _(risk if fails: {step['riskIfFails']})_{mark}",
                      f"      rollback: {step['rollback']}"]
        lines.append("")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    do_render = "--render" in args
    if do_render:
        args.remove("--render")
    if len(args) != 1:
        sys.exit("ERROR: usage: check_plan.py <plan.json> [--render]")
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

    warnings, irreversible = check(plan)
    out = {"plan": plan, "warnings": warnings, "irreversible": irreversible}
    if do_render:
        out["rendered"] = render(plan)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
