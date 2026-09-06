#!/usr/bin/env python3
"""Check an onboarding specification for completeness and render it.

Usage:
    render_onboarding.py <onboarding.json> --out-dir <dir> [--facts-file <orientation.json>] [--env-file <env-var-inventory.json>] [--dry-run]

The input conforms to assets/onboarding.schema.json, this skill's own
intermediate shape (SDS-S-080). The model composes it in the Decide
stage; this script does only what is mechanical (SDS-S-060):

  1. validates the JSON against the asset schema;
  2. refuses (onboarding-incomplete) a setup step whose `verify` is
     blank — a step a newcomer cannot check is where they get stuck
     alone — and an access entry granted by nobody in particular
     ("someone", "TBD", "?");
  3. with --facts-file (the repository-orientation facts object,
     SDS-S-065: injected, never re-collected here), refuses
     (command-undeclared) a setup `command` naming a `make` target or
     npm script the manifests do not declare, and warns when the
     facts show tests but no setup step runs them, or CI the guide
     never mentions;
  4. with --env-file (env-var-inventory's finding-list, injected),
     warns for every variable the code requires that no access or
     setup step mentions — the newcomer would hit it cold;
  5. warns (never fails) when `lastVerified` is absent — nobody has
     followed the guide end to end;
  6. renders <out-dir>/ONBOARDING.md (rung 4, local-write).

`--dry-run` prints everything and writes nothing. Output:
{"path", "warnings", "setupSteps", "rendered"?}. Exit 1 with
"ERROR: ..." on stderr for an unreadable/malformed input
(onboarding-unparseable), a spec failing the shape (onboarding-invalid),
an unverifiable step or anonymous grantor (onboarding-incomplete), an
undeclared command (command-undeclared), an unreadable facts file
(facts-unparseable), an env file that is not env-var-inventory output
(env-unparseable), or a missing output directory (out-dir-missing).
Requires the `jsonschema` package.
"""
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
except ModuleNotFoundError:
    sys.exit("ERROR: the jsonschema package is required (pip install jsonschema)")

MAKE_RE = re.compile(r"(?:^|&&|;|\|\|)\s*make\s+([A-Za-z0-9_./-]+)")
NPM_RE = re.compile(r"(?:^|&&|;|\|\|)\s*(?:npm\s+run|npm|yarn|pnpm)\s+([A-Za-z0-9:_-]+)")
NPM_BUILTINS = {"install", "ci", "test", "start", "init", "publish", "audit", "i", "add", "run"}
ANONYMOUS = {"", "someone", "tbd", "?", "unknown", "n/a", "anyone"}


def load_json(path, code):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: {path}: {e} ({code})")


def declared(facts):
    make, npm = set(), set()
    for m in facts.get("manifests", []):
        names = {c["name"] for c in m.get("commands", [])}
        if m.get("ecosystem") == "make":
            make |= names
        elif m.get("ecosystem") == "npm":
            npm |= names
    return make, npm


def render(spec):
    lines = [f"# Onboarding: {spec['repository']}", "", f"_For {spec['audience']}._", ""]
    if spec.get("lastVerified"):
        lines += [f"_Last followed end to end by a newcomer: {spec['lastVerified']}._", ""]
    else:
        lines += ["_Nobody has yet followed this guide end to end — tell the maintainers where it broke._", ""]
    lines += ["## Access you need first", ""]
    lines += [f"- **{a['what']}** — granted by {a['grantedBy']}" + (f"; {a['how']}" if a.get("how") else "") for a in spec["access"]] or ["- (none beyond repository read access)"]
    lines += ["", "## Setup", ""]
    for i, s in enumerate(spec["setup"], start=1):
        lines += [f"### {i}. {s['do'].splitlines()[0][:80]}", ""]
        if s.get("command"):
            lines += ["```sh", s["command"], "```", ""]
        lines += [f"**You should see:** {s['verify']}", ""]
    ft = spec["firstTask"]
    lines += ["## Your first task", "", ft["description"], "", f"**Done when:** {ft['done']}", ""]
    if ft.get("link"):
        lines += [f"Tracked at {ft['link']}.", ""]
    lines += ["## Who to ask", ""] + [f"- **{w['topic']}:** {w['ask']}" for w in spec["whoToAsk"]] + [""]
    if spec.get("reading"):
        lines += ["## Read next", ""] + [f"- [{r['title']}]({r['where']})" + (f" — {r['why']}" if r.get("why") else "") for r in spec["reading"]] + [""]
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    if dry:
        args.remove("--dry-run")
    out_dir = facts_path = env_path = None
    for flag in ("--out-dir", "--facts-file", "--env-file"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            if flag == "--out-dir":
                out_dir = Path(args[i + 1])
            elif flag == "--facts-file":
                facts_path = args[i + 1]
            else:
                env_path = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or out_dir is None:
        sys.exit("ERROR: usage: render_onboarding.py <onboarding.json> --out-dir <dir> [--facts-file <orientation.json>] [--dry-run]")
    spec = load_json(args[0], "onboarding-unparseable")
    schema = json.loads((Path(__file__).resolve().parent.parent / "assets" / "onboarding.schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.validate(spec, schema)
    except jsonschema.ValidationError as e:
        sys.exit(f"ERROR: specification fails assets/onboarding.schema.json at {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message} (onboarding-invalid)")
    for i, s in enumerate(spec["setup"], start=1):
        if not s.get("verify", "").strip():
            sys.exit(f"ERROR: setup step {i} ({s['do'][:40]!r}) has no verify; a newcomer cannot tell whether it worked (onboarding-incomplete)")
    for a in spec["access"]:
        if a["grantedBy"].strip().lower() in ANONYMOUS:
            sys.exit(f"ERROR: access {a['what']!r} is granted by {a['grantedBy']!r}; name a person, role, or request path (onboarding-incomplete)")
    if not out_dir.is_dir():
        sys.exit(f"ERROR: output directory does not exist (out-dir-missing): {out_dir}")
    warnings = []
    if facts_path:
        facts = load_json(facts_path, "facts-unparseable")
        make, npm = declared(facts)
        for s in spec["setup"]:
            cmd = s.get("command") or ""
            for t in MAKE_RE.findall(cmd):
                if t not in make:
                    sys.exit(f"ERROR: setup: 'make {t}' is not a declared Makefile target (declared: {', '.join(sorted(make)) or 'none'}) (command-undeclared)")
            for n in NPM_RE.findall(cmd):
                if n not in npm and n not in NPM_BUILTINS:
                    sys.exit(f"ERROR: setup: '{n}' is not a declared package.json script (declared: {', '.join(sorted(npm)) or 'none'}) (command-undeclared)")
        sig = facts.get("signals", {})
        text = json.dumps(spec).lower()
        if sig.get("tests") and not any("test" in (s.get("command") or "").lower() or "test" in s["do"].lower() for s in spec["setup"]):
            warnings.append("the repository has tests but no setup step runs them; a newcomer's first signal that setup worked is a green test run")
        if sig.get("ci") and "ci" not in text and "workflow" not in text:
            warnings.append("the repository has CI workflows the guide never mentions")
    else:
        warnings.append("no --facts-file given: setup commands were not checked against the repository's declared ones")
    if env_path:
        # env-var-inventory's finding-list (SDS-S-065: injected, never re-collected): every variable the code requires
        # must be handed to the newcomer somewhere in the guide
        env = load_json(env_path, "env-unparseable")
        try:
            variables = env["runs"][0]["tool"]["properties"]["variables"]
        except (KeyError, IndexError, TypeError):
            sys.exit(f"ERROR: {env_path} is not env-var-inventory output with tool.properties.variables (env-unparseable)")
        guide_text = json.dumps(spec)
        for v in variables:
            if v.get("required") and v["variable"] not in guide_text:
                warnings.append(f"required variable {v['variable']} (env-var-inventory) is mentioned in no access or setup step; the newcomer will hit it cold")
    if not spec.get("lastVerified"):
        warnings.append("lastVerified is absent: nobody has followed this guide end to end")
    rendered = render(spec)
    path = out_dir / "ONBOARDING.md"
    result = {"path": str(path), "warnings": warnings, "setupSteps": len(spec["setup"])}
    if dry:
        result["rendered"] = rendered
    else:
        path.write_text(rendered, encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
