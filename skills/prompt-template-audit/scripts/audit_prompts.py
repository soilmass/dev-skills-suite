#!/usr/bin/env python3
"""Audit the LLM calls in a Python tree for the prompt-engineering
mistakes that cost the most in production, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    audit_prompts.py <repo-path> [--patterns <patterns.json>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): `ast` only; no model is called. An
LLM call is a method call whose name is in the patterns' `callMethods`
(create, generate, complete, invoke, …) and whose keywords include
one of `modelKeywords` or `promptKeywords` (default
assets/llm-call-patterns.json) — shape, not vendor: Anthropic
`client.messages.create(model=…, messages=…)`, OpenAI
`chat.completions.create(...)`, and home-grown wrappers all match.

Rules emitted:

    prompt/unpinned-model        the model argument is not a string
                                 literal, or is one ending in an alias
                                 (-latest, latest) or lacking a
                                 version/date suffix per the patterns'
                                 `pinnedModelPattern` -> warning (the
                                 model changes under you; evals stop
                                 meaning anything)
    prompt/no-max-tokens         no max_tokens / max_output_tokens /
                                 max_completion_tokens keyword -> info
                                 (cost and latency are unbounded)
    prompt/user-input-interpolated a prompt built from an f-string,
                                 %-format, .format(), or concatenation
                                 whose interpolated expression names
                                 user input (user, input, query,
                                 question, message, request, text,
                                 content) and is not wrapped in
                                 delimiters (an XML tag, triple quotes,
                                 or a fenced block) -> warning (prompt
                                 injection surface)
    prompt/no-system-prompt      no `system=` keyword and no message
                                 with role "system" in a literal
                                 messages list -> info
    prompt/inline-template       a prompt string literal over
                                 --inline-limit characters (default 300)
                                 written at the call site -> info (move
                                 it to a versioned template so evals can
                                 pin it)
    prompt/temperature-unset     a call with no temperature keyword on a
                                 model keyword present -> info only when
                                 the patterns file says so
                                 (`reportTemperature`, default false)

`tool.properties` carries the inventory: calls per file, the model
literals seen, and how many calls carry a system prompt. Judging what
matters — a pinned alias the team refreshes deliberately, an
interpolation from a trusted source — is the skill's Analyze stage
(SDS-S-061).

Prints one finding-list; a tree with no LLM calls, or well-formed
ones, yields an empty `results` array (SDS-C-033). Exit 1 with
"ERROR: ..." on stderr for a path that is not a directory
(repo-invalid), a Python file that does not parse
(source-unparseable), or a patterns file that is not the expected
shape (patterns-invalid).
"""
import ast
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
USER_INPUT_RE = re.compile(r"(user|input|query|question|message|request|text|content|body|prompt)", re.I)
DELIM_RE = re.compile(r"(<[a-zA-Z_]+>\s*$|```\s*$|\"\"\"\s*$|'''\s*$)")


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def load_patterns(path):
    try:
        p = json.loads(Path(path).read_text(encoding="utf-8"))
        assert isinstance(p["callMethods"], list) and isinstance(p["modelKeywords"], list) and isinstance(p["promptKeywords"], list)
        p.setdefault("maxTokensKeywords", ["max_tokens", "max_output_tokens", "max_completion_tokens"])
        p.setdefault("pinnedModelPattern", r"\d")
        p.setdefault("reportTemperature", False)
        return p
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: patterns {path} must be {{callMethods, modelKeywords, promptKeywords, ...}} (patterns-invalid): {e}")


def kw(call, names):
    for k in call.keywords:
        if k.arg in names:
            return k
    return None


def interpolations(node):
    """Yield (expression source, text before it) for every interpolation in a prompt expression."""
    if isinstance(node, ast.JoinedStr):
        before = ""
        for v in node.values:
            if isinstance(v, ast.Constant):
                before += str(v.value)
            elif isinstance(v, ast.FormattedValue):
                yield ast.unparse(v.value), before
                before = ""
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant):
        args = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
        parts = re.split(r"%[sdr]", str(node.left.value))
        for i, a in enumerate(args):
            yield ast.unparse(a), parts[i] if i < len(parts) else ""
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format" and isinstance(node.func.value, ast.Constant):
        parts = re.split(r"\{[^}]*\}", str(node.func.value.value))
        for i, a in enumerate(list(node.args) + [k.value for k in node.keywords]):
            yield ast.unparse(a), parts[i] if i < len(parts) else ""
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left_text = str(node.left.value) if isinstance(node.left, ast.Constant) else ""
        if not isinstance(node.right, ast.Constant):
            yield ast.unparse(node.right), left_text
        if not isinstance(node.left, ast.Constant):
            yield ast.unparse(node.left), ""


def prompt_exprs(call, pats):
    """Every expression that carries prompt text in this call."""
    out = []
    for k in call.keywords:
        if k.arg in pats["promptKeywords"] or k.arg == "system":
            v = k.value
            if isinstance(v, (ast.List, ast.Tuple)):
                for el in v.elts:
                    if isinstance(el, ast.Dict):
                        for key, val in zip(el.keys, el.values):
                            if isinstance(key, ast.Constant) and key.value == "content":
                                out.append(val)
                    else:
                        out.append(el)
            else:
                out.append(v)
    return out


def literal_len(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return len(node.value)
    if isinstance(node, ast.JoinedStr):
        return sum(len(str(v.value)) for v in node.values if isinstance(v, ast.Constant))
    return 0


def has_system(call):
    if kw(call, ["system"]) is not None:
        return True
    m = kw(call, ["messages", "input"])
    if m is not None and isinstance(m.value, (ast.List, ast.Tuple)):
        for el in m.value.elts:
            if isinstance(el, ast.Dict):
                for key, val in zip(el.keys, el.values):
                    if isinstance(key, ast.Constant) and key.value == "role" and isinstance(val, ast.Constant) and val.value in ("system", "developer"):
                        return True
    return False


def main():
    args = sys.argv[1:]
    opts = {"--patterns": None, "--exclude": "", "--inline-limit": "300"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: audit_prompts.py <repo-path> [--patterns F] [--exclude dir,dir] [--inline-limit N]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    pats = load_patterns(opts["--patterns"] or str(Path(__file__).resolve().parent.parent / "assets" / "llm-call-patterns.json"))
    try:
        inline_limit = int(opts["--inline-limit"])
    except ValueError:
        sys.exit("ERROR: --inline-limit must be an integer (patterns-invalid)")
    exclude = {x.strip() for x in opts["--exclude"].split(",") if x.strip()}
    pinned = re.compile(pats["pinnedModelPattern"])

    out, calls, models, with_system = [], 0, set(), 0
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
        uri = rel.as_posix()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in pats["callMethods"]):
                continue
            if kw(node, pats["modelKeywords"]) is None and kw(node, pats["promptKeywords"]) is None:
                continue
            calls += 1
            ln = node.lineno
            mk = kw(node, pats["modelKeywords"])
            if mk is not None:
                if isinstance(mk.value, ast.Constant) and isinstance(mk.value.value, str):
                    models.add(mk.value.value)
                    if mk.value.value.endswith("latest") or not pinned.search(mk.value.value):
                        out.append(finding("prompt/unpinned-model", "warning", f"model {mk.value.value!r} is an alias or carries no version; pin a dated or versioned id so evals stay meaningful", uri, ln, {"model": mk.value.value}))
                else:
                    out.append(finding("prompt/unpinned-model", "warning", f"model is not a literal ({ast.unparse(mk.value)[:40]}); the id must be pinned somewhere reviewable", uri, ln, {"model": ast.unparse(mk.value)[:80]}))
            if kw(node, pats["maxTokensKeywords"]) is None:
                out.append(finding("prompt/no-max-tokens", "info", "no max_tokens; cost and latency are unbounded", uri, ln, {}))
            if has_system(node):
                with_system += 1
            else:
                out.append(finding("prompt/no-system-prompt", "info", "no system prompt (no system= and no system-role message); the model's role and limits are unstated", uri, ln, {}))
            if pats.get("reportTemperature") and kw(node, ["temperature"]) is None:
                out.append(finding("prompt/temperature-unset", "info", "no temperature; the default varies by vendor and version", uri, ln, {}))
            for expr in prompt_exprs(node, pats):
                for src, before in interpolations(expr):
                    if USER_INPUT_RE.search(src) and not DELIM_RE.search(before.rstrip() if before else ""):
                        out.append(finding("prompt/user-input-interpolated", "warning", f"prompt interpolates {src!r} with no delimiter before it; wrap user-supplied text in a tag or fence so instructions and data are separable", uri, expr.lineno, {"expression": src[:80]}))
                if literal_len(expr) > inline_limit:
                    out.append(finding("prompt/inline-template", "info", f"a {literal_len(expr)}-character prompt is written at the call site; move it to a versioned template so evals can pin it", uri, expr.lineno, {"length": literal_len(expr)}))
    order = {"warning": 0, "info": 1}
    out.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "prompt-template-audit", "version": "0.1.0"},
                                         "properties": {"calls": calls, "models": sorted(models), "callsWithSystemPrompt": with_system}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
