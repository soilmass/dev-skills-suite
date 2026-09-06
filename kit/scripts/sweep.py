#!/usr/bin/env python3
"""Run every applicable Query Skill's Gather against one repository and
digest the results — the machine half of "run every audit on this repo".

Usage:
    sweep.py <repo> [--only a,b] [--skip a,b] [--out <dir>]
             [--needs git,osv] [--extra skill=args ...] [--timeout N]

Reads `kit/registry/sweep.json` (validated at startup: every key besides
`excluded` and `_comment` must name an existing `skills/<name>/` whose
registered script(s) exist under its `scripts/`, else exit 2 naming the
bad entry). For each registered skill, in name order, the command is
built as `python3 scripts/<script> <abs repo path> <args>` (a
`"pipeline"` entry — currently only dependency-audit's three-script
chain — is run through `bash -c` instead, with `{repo}` substituted for
the absolute repository path and `{extra}` for any `--extra` text) and
run with cwd set to `skills/<skill>/`.

A skill whose `needs` (e.g. `git`, `osv`) are not all named on `--needs`
is skipped and reported, not run — `--needs` defaults to empty, so
git- and network-dependent entries are opt-in. `--only` and `--skip`
take comma-separated skill names to narrow the registered set. `--extra
<skill>=<args>` appends extra arguments to one skill's run (repeatable);
the registry's own `args` stay repository-agnostic on purpose. `--out`
is where per-skill output goes; when omitted, a fresh temp directory is
created and printed at the end — the target repository is never written
into, whether the default is used or a `--out` is given. `--timeout`
(default 300s) bounds each script; a timeout is treated like a crash.

For each skill: exit 0 output is captured to `<out>/<skill>.json`; a
non-zero exit writes stderr to `<out>/<skill>.error.txt`. One line is
printed per skill: `OK <skill> (<n> results)` (freeform-shape skills
print `OK <skill> (freeform)`, since there is no `results` array to
count), `ERROR <skill>: <first stderr line>`, or `SKIP <skill> (needs
...)`. A script's own `ERROR: ...`-and-exit-1 is reported and counted
in this way, not fatal to the sweep.

`skills/findings-digest/scripts/digest_findings.py` is then run over
every `<out>/<skill>.json` whose registry `shape` is `finding-list`
(freeform outputs, e.g. repository-orientation, are excluded from the
digest though they still ran); its stdout is written to `<out>/digest.json`
and its `summary` plus its "Totals" and "By tool" sections are printed.

Exit 0 even when audits find things, and even when an individual
script's own `ERROR: ...` exit was reported. Exit 1 only when a script
crashed (a non-zero exit whose stderr does not start with `ERROR:`, or
a timeout) or the digest itself failed. Exit 2 on a usage or registry
error.
"""
import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

FAMILY_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = FAMILY_ROOT / "kit" / "registry" / "sweep.json"
DIGEST_SCRIPT = FAMILY_ROOT / "skills" / "findings-digest" / "scripts" / "digest_findings.py"
DEFAULT_TIMEOUT = 300
PIPELINE_SCRIPT_RE = re.compile(r"scripts/(\S+\.py)")


def die(msg: str, code: int = 2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def load_registry():
    try:
        raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except OSError as e:
        die(f"ERROR: could not read {REGISTRY_PATH} (registry-missing): {e}")
    except json.JSONDecodeError as e:
        die(f"ERROR: {REGISTRY_PATH} is not valid JSON (registry-invalid): {e}")
    excluded = raw.pop("excluded", {})
    raw.pop("_comment", None)
    return raw, excluded


def validate_registry(registry: dict) -> None:
    for name, entry in sorted(registry.items()):
        skill_dir = FAMILY_ROOT / "skills" / name
        if not skill_dir.is_dir():
            die(f"ERROR: registry entry {name!r} names a skill that does not exist: {skill_dir.relative_to(FAMILY_ROOT)} (registry-invalid)")
        if "pipeline" in entry:
            scripts = PIPELINE_SCRIPT_RE.findall(entry["pipeline"])
            if not scripts:
                die(f"ERROR: registry entry {name!r} has a pipeline with no scripts/*.py reference (registry-invalid)")
            for s in scripts:
                if not (skill_dir / "scripts" / s).is_file():
                    die(f"ERROR: registry entry {name!r} pipeline references missing script scripts/{s} (registry-invalid)")
        elif "script" in entry:
            if not (skill_dir / "scripts" / entry["script"]).is_file():
                die(f"ERROR: registry entry {name!r} references missing script scripts/{entry['script']} (registry-invalid)")
        else:
            die(f"ERROR: registry entry {name!r} has neither 'script' nor 'pipeline' (registry-invalid)")
        if entry.get("shape") not in ("finding-list", "freeform"):
            die(f"ERROR: registry entry {name!r} has an unrecognized shape {entry.get('shape')!r} (registry-invalid)")


def first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return "(no stderr)"


def count_results(shape: str, stdout: str):
    if shape == "freeform":
        return None
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        return 0
    if isinstance(doc, dict) and isinstance(doc.get("runs"), list):
        return sum(len(run.get("results") or []) for run in doc["runs"] if isinstance(run, dict))
    return 0


def run_one(name: str, entry: dict, repo: Path, extra: str, timeout: int, out_dir: Path):
    skill_dir = FAMILY_ROOT / "skills" / name
    if "pipeline" in entry:
        cmd_str = entry["pipeline"].replace("{repo}", shlex.quote(str(repo))).replace("{extra}", extra)
        popen_args = ["bash", "-c", cmd_str]
    else:
        args_tail = shlex.split(entry.get("args", "")) + shlex.split(extra)
        popen_args = ["python3", f"scripts/{entry['script']}", str(repo)] + args_tail
    try:
        r = subprocess.run(popen_args, cwd=skill_dir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "crash", None, f"timed out after {timeout}s"
    if r.returncode == 0:
        return "ok", r.stdout, None
    reason = first_line(r.stderr)
    kind = "error" if reason.startswith("ERROR:") else "crash"
    return kind, r.stdout, (r.stderr or reason)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo", help="repository to sweep")
    ap.add_argument("--only", help="comma-separated skill names to run (default: all registered)")
    ap.add_argument("--skip", help="comma-separated skill names to skip")
    ap.add_argument("--out", help="output directory (default: a fresh temp dir, printed at the end)")
    ap.add_argument("--needs", default="", help="comma-separated gates to opt into, e.g. git,osv (default: none)")
    ap.add_argument("--extra", action="append", default=[], metavar="skill=args", help="extra arguments for one skill's run (repeatable)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"per-script timeout in seconds (default {DEFAULT_TIMEOUT})")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    if not repo.is_dir():
        die(f"ERROR: not a directory: {repo} (repo-invalid)")

    out_dir = Path(a.out).resolve() if a.out else Path(tempfile.mkdtemp(prefix="sweep-"))
    try:
        out_dir.relative_to(repo)
        die(f"ERROR: --out {out_dir} is inside the target repository {repo}; sweep output must never be written there (out-invalid)")
    except ValueError:
        pass
    out_dir.mkdir(parents=True, exist_ok=True)

    registry, excluded_map = load_registry()
    validate_registry(registry)

    only = set(a.only.split(",")) if a.only else None
    skip = set(a.skip.split(",")) if a.skip else set()
    granted = {n for n in a.needs.split(",") if n}
    extras = {}
    for item in a.extra:
        if "=" not in item:
            die(f"ERROR: --extra must be skill=args, got {item!r} (usage)")
        k, v = item.split("=", 1)
        extras[k] = v

    names = sorted(registry)
    if only is not None:
        unknown = only - set(names)
        if unknown:
            print(f"NOTE: --only names not in the registry, ignored: {', '.join(sorted(unknown))}", file=sys.stderr)
        names = [n for n in names if n in only]
    names = [n for n in names if n not in skip]

    crashed = False
    digest_inputs = []
    for name in names:
        entry = registry[name]
        needs = entry.get("needs", [])
        missing = [n for n in needs if n not in granted]
        if missing:
            print(f"SKIP {name} (needs {', '.join(missing)})")
            continue
        kind, stdout, err = run_one(name, entry, repo, extras.get(name, ""), a.timeout, out_dir)
        if kind == "ok":
            (out_dir / f"{name}.json").write_text(stdout, encoding="utf-8")
            n = count_results(entry.get("shape"), stdout)
            if entry.get("shape") == "finding-list":
                digest_inputs.append(out_dir / f"{name}.json")
                print(f"OK {name} ({n} results)")
            else:
                print(f"OK {name} (freeform)")
        else:
            (out_dir / f"{name}.error.txt").write_text(err or "", encoding="utf-8")
            print(f"ERROR {name}: {first_line(err or '')}")
            if kind == "crash":
                crashed = True

    if digest_inputs:
        digest_cmd = ["python3", str(DIGEST_SCRIPT)] + [str(p) for p in digest_inputs]
        r = subprocess.run(digest_cmd, cwd=FAMILY_ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ERROR: digest failed: {first_line(r.stderr)}", file=sys.stderr)
            crashed = True
        else:
            (out_dir / "digest.json").write_text(r.stdout, encoding="utf-8")
            try:
                digest = json.loads(r.stdout)
            except json.JSONDecodeError:
                print("ERROR: digest failed: digest output was not valid JSON", file=sys.stderr)
                crashed = True
                digest = None
            if digest is not None:
                print()
                print(digest.get("summary", ""))
                for section in digest.get("sections", []):
                    if section.get("heading") in ("Totals", "By tool"):
                        print(f"\n{section['heading']}:")
                        print(section.get("body", ""))
    else:
        print("\nNo finding-list outputs to digest.")

    print(f"\nsweep output: {out_dir}")
    sys.exit(1 if crashed else 0)


if __name__ == "__main__":
    main()
