#!/usr/bin/env python3
"""Run every executable eval row of a skill (or the family) and check
the outcome against the row's expectation — the machine half of the
validation gate's "eval table passes" (SDS-S-110).

Usage:
    run-evals.py <skill-dir> [--skip-generators] [--timeout N] [--verbose]
                 [--json] [--sarif]
    run-evals.py --all <skills-dir> [same options]

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

`--json` emits a `finding-list` document (kit/shapes/finding-list.schema.json)
to stdout instead — driver name `run-evals` — with one result per FAILED
row: `ruleId` `eval/<row-name>`, `level` `error`, `message.text` the same
failure reason the text mode prints, `locations[0]` pointing at the
skill's eval YAML file and the row's exact `- name:` line, and
`properties.skill` naming the skill. A generator (`GEN FAIL`) or setup
(`SETUP FAIL`, e.g. a missing eval file) failure also gets one result —
`ruleId` `eval/generator/<script-name>` or `eval/setup`, located at the
generator script or the eval file — so `--json` never exits 1 with an
empty `results` array. The usual per-row/per-skill text goes to stderr
instead of stdout so stdout is the one JSON document; the document is
self-validated against the schema before printing (exit 2 if it does
not validate); the exit code otherwise stays 1 on any failure.
`--sarif` (only meaningful with `--json`) emits the SARIF-2.1.0 variant
of that document instead: `version` becomes `"2.1.0"` and a top-level
`$schema` of `https://json.schemastore.org/sarif-2.1.0.json` is added,
for upload to GitHub Code Scanning.
"""
import argparse
import json
import re
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
RUNNER_VERSION = "0.1.0"


def load_rows(skill: Path):
    f = skill / "evals" / f"{skill.name}.eval.yaml"
    if not f.is_file():
        return None, f"no eval file {f.relative_to(FAMILY_ROOT)}"
    docs = list(yaml.safe_load_all(f.read_text(encoding="utf-8")))
    table = docs[0] if docs else {}
    return (table or {}).get("rows") or [], None


def run_generators(skill: Path, timeout: int, verbose: bool, out=sys.stdout, findings=None):
    ok = True
    for gen in sorted((skill / "evals" / "fixtures").glob("build-*.sh")):
        r = subprocess.run(["bash", str(gen)], cwd=skill, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            ok = False
            reason = f"exit {r.returncode}"
            print(f"  GEN  FAIL {gen.relative_to(skill)} ({reason})", file=out)
            if verbose:
                print("       " + r.stderr.strip().replace("\n", "\n       "), file=out)
            if findings is not None:
                findings.append({
                    "ruleId": f"eval/generator/{gen.name}",
                    "level": "error",
                    "message": {"text": reason},
                    "locations": [{"physicalLocation": {"artifactLocation": {"uri": str(gen.relative_to(FAMILY_ROOT))}}}],
                    "properties": {"skill": str(skill.relative_to(FAMILY_ROOT))},
                })
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


def find_row_line(eval_lines, name):
    """Line number of a row's `- name: <name>` line: match the YAML value
    exactly (optionally quoted, optional trailing `# comment`), anchored
    to the end of the line, so a lookup for `foo` cannot match a `foo-bar`
    row that happens to appear first in the file. `None` if no row
    declares this exact name."""
    if eval_lines is None:
        return None
    pat = re.compile(r"^\s*-\s*name:\s*['\"]?" + re.escape(name) + r"['\"]?\s*(#.*)?$")
    for i, line in enumerate(eval_lines):
        if pat.match(line):
            return i + 1
    return None


def make_finding(skill: Path, eval_file: Path, eval_lines, name: str, message: str) -> dict:
    loc = {"physicalLocation": {"artifactLocation": {"uri": str(eval_file.relative_to(FAMILY_ROOT))}}}
    line = find_row_line(eval_lines, name)
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {
        "ruleId": f"eval/{name}",
        "level": "error",
        "message": {"text": message},
        "locations": [loc],
        "properties": {"skill": str(skill.relative_to(FAMILY_ROOT))},
    }


def run_skill(skill: Path, args, out=sys.stdout, findings=None):
    eval_file = skill / "evals" / f"{skill.name}.eval.yaml"
    rows, err = load_rows(skill)
    print(f"== {skill.relative_to(FAMILY_ROOT)}", file=out)
    if err:
        print(f"  SETUP FAIL {err}", file=out)
        if findings is not None:
            findings.append({
                "ruleId": "eval/setup",
                "level": "error",
                "message": {"text": err},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": str(eval_file.relative_to(FAMILY_ROOT))}}}],
                "properties": {"skill": str(skill.relative_to(FAMILY_ROOT))},
            })
        return 0, 1, 0
    if not args.skip_generators and not run_generators(skill, args.timeout, args.verbose, out=out, findings=findings):
        return 0, 1, 0
    eval_lines = eval_file.read_text(encoding="utf-8").splitlines() if findings is not None and eval_file.is_file() else None
    passed = failed = skipped = 0
    for row in rows:
        name = row.get("name", "<unnamed>")
        cmd = ((row.get("input") or {}).get("command")) if isinstance(row.get("input"), dict) else None
        if (row.get("expected") or {}).get("kind") == "not-applicable" or not cmd:
            skipped += 1
            print(f"  SKIP {name}", file=out)
            continue
        # A folded YAML scalar keeps the newlines of its more-indented
        # continuation lines; the row means one command line.
        cmd = " ".join(cmd.split())
        try:
            r = subprocess.run(["bash", "-c", cmd], cwd=skill, capture_output=True, text=True, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            failed += 1
            reason = f"timed out after {args.timeout}s"
            print(f"  FAIL {name}: {reason}", file=out)
            if findings is not None:
                findings.append(make_finding(skill, eval_file, eval_lines, name, reason))
            continue
        ok, why = judge(row, r, True)
        if ok:
            passed += 1
            print(f"  PASS {name} ({why})", file=out)
        else:
            failed += 1
            print(f"  FAIL {name}: {why}", file=out)
            if args.verbose and r.stderr.strip():
                print("       " + r.stderr.strip()[-800:].replace("\n", "\n       "), file=out)
            if findings is not None:
                findings.append(make_finding(skill, eval_file, eval_lines, name, why))
    print(f"  -- {passed} passed, {failed} failed, {skipped} skipped", file=out)
    return passed, failed, skipped


def emit_json(findings: list[dict], sarif: bool) -> int:
    doc = {"version": "sds-finding-list-1.0",
           "runs": [{"tool": {"driver": {"name": "run-evals", "version": RUNNER_VERSION}}, "results": findings}]}
    schema_p = SHAPES / "finding-list.schema.json"
    try:
        jsonschema.validate(doc, json.loads(schema_p.read_text(encoding="utf-8")))
    except (jsonschema.ValidationError, json.JSONDecodeError) as e:
        sys.stderr.write(f"ERROR: runner output failed finding-list schema validation: {str(e)[:120]}\n")
        return 2
    if sarif:
        doc = {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0", "runs": doc["runs"]}
    print(json.dumps(doc, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("skill", nargs="?", help="skill directory")
    ap.add_argument("--all", metavar="SKILLS_DIR", help="run every skill under this directory")
    ap.add_argument("--skip-generators", action="store_true")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true", help="emit a finding-list document (one result per failed row); per-row text goes to stderr")
    ap.add_argument("--sarif", action="store_true", help="with --json, emit the SARIF 2.1.0 variant for GitHub Code Scanning upload")
    a = ap.parse_args()
    if bool(a.skill) == bool(a.all):
        ap.error("give exactly one of <skill-dir> or --all <skills-dir>")
    targets = sorted(p for p in Path(a.all).iterdir() if (p / "SKILL.md").is_file()) if a.all else [Path(a.skill)]
    if not targets or any(not t.is_dir() for t in targets):
        sys.exit(2)
    out = sys.stderr if a.json else sys.stdout
    findings = [] if a.json else None
    totals = [0, 0, 0]
    for t in targets:
        for i, n in enumerate(run_skill(t.resolve(), a, out=out, findings=findings)):
            totals[i] += n
    print(f"TOTAL {len(targets)} skill(s): {totals[0]} passed, {totals[1]} failed, {totals[2]} skipped", file=out)
    if a.json:
        rc = emit_json(findings, a.sarif)
        if rc:
            sys.exit(rc)
    sys.exit(1 if totals[1] else 0)


if __name__ == "__main__":
    main()
