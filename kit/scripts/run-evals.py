#!/usr/bin/env python3
"""Run every executable eval row of a skill (or the family) and check
the outcome against the row's expectation — the machine half of the
validation gate's "eval table passes" (SDS-S-110).

Usage:
    run-evals.py <skill-dir> [--skip-generators] [--timeout N] [--verbose]
    run-evals.py --all <skills-dir> [--skip-generators] [--timeout N] [--verbose]

Requires pyyaml and jsonschema (the linter's dependencies). For each
skill: the generators `evals/fixtures/build-*.sh` are run first (they
are idempotent by SDS-S-096; `--skip-generators` skips them), then
every row of `evals/<name>.eval.yaml` that carries `input.command` is
run with bash from the skill directory (SDS-F-031) and judged by
`expected.kind`:

    success         exit code 0; when `expected.shape` names a
                    registered shape and stdout is JSON, stdout must
                    validate against kit/shapes/<shape>.schema.json
    failure         exit code non-zero, and `expected.failureCode`
                    must appear on stderr (a code that does not is
                    reported as a failed row: the code the skill
                    documents is the code the script must emit)
    not-applicable  skipped, counted

The smoke section after the YAML `---` separator is never run
(SDS-S-092): those rows are live. Assertions are prose for the
reviewer and are not evaluated here.

Output: one line per row (PASS / FAIL / SKIP) and a summary per skill;
exit 0 when every executed row passed, 1 when any failed, 2 on a
usage or setup error. `--verbose` prints the stderr of failed rows.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    import jsonschema
    import yaml
except ImportError as e:  # pragma: no cover
    sys.exit(f"ERROR: run-evals.py needs pyyaml and jsonschema: {e}")

FAMILY_ROOT = Path(__file__).resolve().parent.parent.parent
SHAPES = FAMILY_ROOT / "kit" / "shapes"
ENVELOPE_KEYS = ("decision", "report", "plan", "document", "artifact")


def load_rows(skill: Path):
    f = skill / "evals" / f"{skill.name}.eval.yaml"
    if not f.is_file():
        return None, f"no eval file {f.relative_to(FAMILY_ROOT)}"
    docs = list(yaml.safe_load_all(f.read_text(encoding="utf-8")))
    table = docs[0] if docs else {}
    return (table or {}).get("rows") or [], None


def run_generators(skill: Path, timeout: int, verbose: bool):
    ok = True
    for gen in sorted((skill / "evals" / "fixtures").glob("build-*.sh")):
        r = subprocess.run(["bash", str(gen)], cwd=skill, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            ok = False
            print(f"  GEN  FAIL {gen.relative_to(skill)} (exit {r.returncode})")
            if verbose:
                print("       " + r.stderr.strip().replace("\n", "\n       "))
    return ok


def judge(row, r, shape_ok):
    exp = row.get("expected") or {}
    kind = exp.get("kind")
    if kind == "success":
        if r.returncode != 0:
            return False, f"exit {r.returncode}, expected 0"
        shape = exp.get("shape")
        if shape and (SHAPES / f"{shape}.schema.json").is_file() and r.stdout.lstrip().startswith(("{", "[")):
            try:
                doc = json.loads(r.stdout)
            except json.JSONDecodeError:
                return True, "exit 0 (stdout not a single JSON document; shape not checked)"
            schema = json.loads((SHAPES / f"{shape}.schema.json").read_text(encoding="utf-8"))
            try:
                jsonschema.validate(doc, schema)
                return True, f"exit 0, {shape} valid"
            except jsonschema.ValidationError as e:
                top_err = e.message[:120]
            # A Command Skill's dry-run or check output wraps the artifact in
            # an envelope ({path, warnings, report: {...}}); validate the
            # member that carries it.
            for key in ENVELOPE_KEYS:
                if isinstance(doc, dict) and isinstance(doc.get(key), dict):
                    try:
                        jsonschema.validate(doc[key], schema)
                        return True, f"exit 0, {shape} valid inside envelope key {key!r}"
                    except jsonschema.ValidationError as e:
                        return False, f"stdout[{key!r}] does not validate against {shape}: {e.message[:120]}"
            return False, f"stdout does not validate against {shape}: {top_err}"
        return True, "exit 0"
    if kind == "failure":
        if r.returncode == 0:
            return False, "exit 0, expected non-zero"
        code = exp.get("failureCode")
        if code and code not in r.stderr:
            return False, f"exit {r.returncode} but stderr lacks failureCode {code!r}"
        return True, f"exit {r.returncode}, {code or 'no code'} on stderr"
    return False, f"unknown expected.kind {kind!r}"


def run_skill(skill: Path, args):
    rows, err = load_rows(skill)
    print(f"== {skill.relative_to(FAMILY_ROOT)}")
    if err:
        print(f"  SETUP FAIL {err}")
        return 0, 1, 0
    if not args.skip_generators and not run_generators(skill, args.timeout, args.verbose):
        return 0, 1, 0
    passed = failed = skipped = 0
    for row in rows:
        name = row.get("name", "<unnamed>")
        cmd = ((row.get("input") or {}).get("command")) if isinstance(row.get("input"), dict) else None
        if (row.get("expected") or {}).get("kind") == "not-applicable" or not cmd:
            skipped += 1
            print(f"  SKIP {name}")
            continue
        # A folded YAML scalar keeps the newlines of its more-indented
        # continuation lines; the row means one command line.
        cmd = " ".join(cmd.split())
        try:
            r = subprocess.run(["bash", "-c", cmd], cwd=skill, capture_output=True, text=True, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            failed += 1
            print(f"  FAIL {name}: timed out after {args.timeout}s")
            continue
        ok, why = judge(row, r, True)
        if ok:
            passed += 1
            print(f"  PASS {name} ({why})")
        else:
            failed += 1
            print(f"  FAIL {name}: {why}")
            if args.verbose and r.stderr.strip():
                print("       " + r.stderr.strip()[-800:].replace("\n", "\n       "))
    print(f"  -- {passed} passed, {failed} failed, {skipped} skipped")
    return passed, failed, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("skill", nargs="?", help="skill directory")
    ap.add_argument("--all", metavar="SKILLS_DIR", help="run every skill under this directory")
    ap.add_argument("--skip-generators", action="store_true")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if bool(a.skill) == bool(a.all):
        ap.error("give exactly one of <skill-dir> or --all <skills-dir>")
    targets = sorted(p for p in Path(a.all).iterdir() if (p / "SKILL.md").is_file()) if a.all else [Path(a.skill)]
    if not targets or any(not t.is_dir() for t in targets):
        sys.exit(2)
    totals = [0, 0, 0]
    for t in targets:
        for i, n in enumerate(run_skill(t.resolve(), a)):
            totals[i] += n
    print(f"TOTAL {len(targets)} skill(s): {totals[0]} passed, {totals[1]} failed, {totals[2]} skipped")
    sys.exit(1 if totals[1] else 0)


if __name__ == "__main__":
    main()
