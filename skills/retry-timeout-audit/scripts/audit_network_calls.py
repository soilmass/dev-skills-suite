#!/usr/bin/env python3
"""Audit a Python tree's network calls for missing timeouts and unsafe
retry loops, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    audit_network_calls.py <repo-path> [--patterns <patterns.json>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): `ast` only; nothing is called. A
network call is a call whose callee matches the patterns'
`networkCalls` (assets/network-calls.json by default): dotted names
resolved through imports and aliases (`requests.get`, `httpx.post`,
`urllib.request.urlopen`, `socket.create_connection`), plus method
names on any receiver in `clientMethods` (`.get`, `.post`, … on a
variable assigned from `requests.Session()` / `httpx.Client()`).

Rules emitted:

    net/no-timeout          a network call with no `timeout` keyword
                            (and no timeout configured on its client
                            constructor when the receiver is a client
                            variable) -> warning; a hung peer hangs the
                            caller forever
    net/subprocess-no-timeout subprocess.run / check_output / call
                            without timeout -> info
    net/constant-backoff    a loop that contains a network call and a
                            `time.sleep(<constant>)` -> info; retries
                            at a fixed interval synchronise and pile on
                            a struggling peer (use exponential backoff
                            with jitter)
    net/unbounded-retry     a `while True` loop that contains a network
                            call and an `except` handler that continues
                            the loop, with no `break` under a counter
                            -> warning; a peer that is down is retried
                            forever
    net/broad-retry         a retry loop whose handler catches
                            `Exception` / bare `except` -> info;
                            programming errors get retried too

`tool.properties` carries the inventory: network calls per file and
how many carry a timeout. Judging what matters — a script that is
allowed to hang, a client whose timeout is set in a wrapper the audit
cannot see — is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; a tree with no network calls, or safe ones,
yields an empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..."
on stderr for a path that is not a directory (repo-invalid), a Python
file that does not parse (source-unparseable), or a patterns file that
is not the expected shape (patterns-invalid).
"""
import ast
import json
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def load_patterns(path):
    try:
        p = json.loads(Path(path).read_text(encoding="utf-8"))
        assert isinstance(p["networkCalls"], list) and isinstance(p["clientConstructors"], list) and isinstance(p["clientMethods"], list)
        return p
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: patterns {path} must be {{networkCalls, clientConstructors, clientMethods}} (patterns-invalid): {e}")


def dotted(node, aliases):
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        base = aliases.get(cur.id, cur.id)
        return ".".join([base] + list(reversed(parts)))
    return None


def has_kw(call, name):
    return any(k.arg == name for k in call.keywords)


class Auditor(ast.NodeVisitor):
    def __init__(self, uri, pats, out):
        self.uri, self.pats, self.out = uri, pats, out
        self.aliases, self.clients = {}, {}  # var -> constructor had timeout?
        self.calls = 0
        self.with_timeout = 0
        self.loop_stack = []
        self.handler_depth = 0

    def visit_Import(self, node):
        for a in node.names:
            self.aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]

    def visit_ImportFrom(self, node):
        if node.module:
            for a in node.names:
                self.aliases[a.asname or a.name] = f"{node.module}.{a.name}"

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call):
            name = dotted(node.value.func, self.aliases)
            if name in self.pats["clientConstructors"]:
                self.clients[node.targets[0].id] = has_kw(node.value, "timeout")
        self.generic_visit(node)

    def is_network(self, call):
        name = dotted(call.func, self.aliases)
        if name in self.pats["networkCalls"]:
            return name, None
        if isinstance(call.func, ast.Attribute) and call.func.attr in self.pats["clientMethods"] and isinstance(call.func.value, ast.Name) and call.func.value.id in self.clients:
            return f"{call.func.value.id}.{call.func.attr}", call.func.value.id
        return None, None

    def visit_Call(self, node):
        name, client = self.is_network(node)
        if name:
            self.calls += 1
            timed = has_kw(node, "timeout") or (client is not None and self.clients.get(client))
            if timed:
                self.with_timeout += 1
            else:
                self.out.append(finding("net/no-timeout", "warning", f"{name}(...) has no timeout; a hung peer hangs this caller forever", self.uri, node.lineno, {"call": name}))
            if self.loop_stack:
                self.loop_stack[-1]["calls"].append(node.lineno)
        else:
            sub = dotted(node.func, self.aliases)
            if sub in ("subprocess.run", "subprocess.check_output", "subprocess.call", "subprocess.check_call") and not has_kw(node, "timeout"):
                self.out.append(finding("net/subprocess-no-timeout", "info", f"{sub}(...) has no timeout", self.uri, node.lineno, {"call": sub}))
            if sub in ("time.sleep", "sleep") and self.loop_stack and node.args and isinstance(node.args[0], ast.Constant):
                self.loop_stack[-1]["constant_sleeps"].append(node.lineno)
        self.generic_visit(node)

    def _loop(self, node, unbounded):
        frame = {"calls": [], "constant_sleeps": [], "unbounded": unbounded, "handlers": [], "breaks": 0}
        self.loop_stack.append(frame)
        self.generic_visit(node)
        self.loop_stack.pop()
        if not frame["calls"]:
            return
        if frame["constant_sleeps"]:
            self.out.append(finding("net/constant-backoff", "info", f"retry loop sleeps a constant ({len(frame['constant_sleeps'])} time.sleep with a literal); use exponential backoff with jitter", self.uri, node.lineno, {"sleeps": frame["constant_sleeps"]}))
        if frame["handlers"]:
            if unbounded and frame["breaks"] == 0:
                self.out.append(finding("net/unbounded-retry", "warning", "while True retries a network call on every exception with no break; a peer that is down is retried forever", self.uri, node.lineno, {"handlers": frame["handlers"]}))
            if any(h["broad"] for h in frame["handlers"]):
                self.out.append(finding("net/broad-retry", "info", "the retry handler catches Exception (or everything); programming errors get retried too", self.uri, node.lineno, {}))

    def visit_While(self, node):
        self._loop(node, isinstance(node.test, ast.Constant) and node.test.value is True)

    def visit_For(self, node):
        self._loop(node, False)

    def visit_ExceptHandler(self, node):
        if self.loop_stack:
            broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"))
            self.loop_stack[-1]["handlers"].append({"line": node.lineno, "broad": broad})
        self.handler_depth += 1
        self.generic_visit(node)
        self.handler_depth -= 1

    # only an exit on the failure path (inside the handler) bounds a retry loop;
    # a return on success says nothing about what happens when the peer is down
    def visit_Break(self, node):
        if self.loop_stack and self.handler_depth:
            self.loop_stack[-1]["breaks"] += 1

    def visit_Return(self, node):
        if self.loop_stack and self.handler_depth:
            self.loop_stack[-1]["breaks"] += 1
        self.generic_visit(node)

    def visit_Raise(self, node):
        if self.loop_stack and self.handler_depth:
            self.loop_stack[-1]["breaks"] += 1
        self.generic_visit(node)


def main():
    args = sys.argv[1:]
    opts = {"--patterns": None, "--exclude": ""}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: audit_network_calls.py <repo-path> [--patterns F] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    pats = load_patterns(opts["--patterns"] or str(Path(__file__).resolve().parent.parent / "assets" / "network-calls.json"))
    exclude = {x.strip() for x in opts["--exclude"].split(",") if x.strip()}
    out, total, timed, per_file = [], 0, 0, {}
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as e:
            sys.exit(f"ERROR: {rel.as_posix()} does not parse (source-unparseable): {e}")
        a = Auditor(rel.as_posix(), pats, out)
        a.visit(tree)
        if a.calls:
            per_file[rel.as_posix()] = a.calls
        total += a.calls
        timed += a.with_timeout
    order = {"warning": 0, "info": 1}
    out.sort(key=lambda r: (order[r["level"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"]["region"]["startLine"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "retry-timeout-audit", "version": "0.1.0"},
                                         "properties": {"networkCalls": total, "withTimeout": timed, "perFile": per_file}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
