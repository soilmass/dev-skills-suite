#!/usr/bin/env python3
"""Propose the edits that bring a GitHub Projects (v2) board in line with
the repository's issues and pull requests, as a plan-doc
(kit/shapes/plan-doc.schema.json).

Usage:
    propose_board_sync.py <repo-path> --project <number> --owner <login>
    propose_board_sync.py <repo-path> --board-json-file <path>

This is the deterministic part of project-board-sync's Decide stage
(SDS-C-060): a fixed rule table from item facts to a target Status,
diffed against the board. The model's Analyze stage revises the plan
before anything is applied, and every application is a direct, gated
tool call outside this script (SDS-S-051). The script never writes to
GitHub: rung 3 live (reads only), rung 1 with a fixture.

Live mode reads:
    gh project view <n> --owner <o> --format json
    gh project field-list <n> --owner <o> --format json
    gh project item-list <n> --owner <o> --format json --limit 500
    gh issue list --state all --limit 500 --json number,title,state,assignees,labels,url
    gh pr list --state all --limit 500 --json number,title,state,isDraft,reviewDecision,url
`--board-json-file` (SDS-S-065) replaces all five with one file:
    {"project": {"id", "number", "title"},
     "fields": [{"id", "name", "options": [{"id", "name"}]}],
     "items":  [{"id", "content": {"type", "number"}, "status"}],
     "issues": [...], "prs": [...]}

Status rule table (target column per item; assets/status-map.json
maps these keys to the board's column names):
    PR merged, or issue closed                   -> done
    PR closed without merge                      -> (leave the board;
                                                     drop nothing)
    PR open, draft                               -> inProgress
    PR open, not draft                           -> inReview
    issue open with an assignee                  -> inProgress
    issue open, unassigned                       -> todo
Plan steps:
    an open issue/PR not on the board            -> add (then set status)
    an item whose status differs from the target -> set status
    an item already at its target                -> no step
Every step carries its rollback: an added item is removed with
`gh project item-delete`; a status change is reverted by setting the
previous status back. Items whose content is not an issue or PR of
this repository (draft notes, other repositories) are left alone.

Prints one plan-doc; a board already in sync yields a single
"nothing to do" phase (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a path that is not a directory (repo-invalid), a fixture missing
any of the five keys (board-unparseable), a board without a
single-select Status field or one lacking a mapped column
(status-field-missing), or a failed live call (gh-unreachable).
"""
import json
import subprocess
import sys
from pathlib import Path


def load_map():
    return json.loads((Path(__file__).resolve().parent.parent / "assets" / "status-map.json").read_text(encoding="utf-8"))


def gh_json(args, cwd):
    r = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: gh {' '.join(args[:3])} failed (gh-unreachable): {r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: gh {' '.join(args[:2])} returned unparseable JSON (board-unparseable): {e}")


def load_live(repo, number, owner):
    p = ["project"]
    return {
        "project": gh_json(p + ["view", number, "--owner", owner, "--format", "json"], repo),
        "fields": gh_json(p + ["field-list", number, "--owner", owner, "--format", "json"], repo).get("fields", []),
        "items": gh_json(p + ["item-list", number, "--owner", owner, "--format", "json", "--limit", "500"], repo).get("items", []),
        "issues": gh_json(["issue", "list", "--state", "all", "--limit", "500", "--json", "number,title,state,assignees,labels,url"], repo),
        "prs": gh_json(["pr", "list", "--state", "all", "--limit", "500", "--json", "number,title,state,isDraft,reviewDecision,url"], repo),
    }


def load_fixture(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load board file {path} (board-unparseable): {e}")
    missing = [k for k in ("project", "fields", "items", "issues", "prs") if k not in (data if isinstance(data, dict) else {})]
    if missing:
        sys.exit(f"ERROR: board file {path} lacks {', '.join(missing)} (board-unparseable)")
    return data


def status_field(fields, columns):
    for f in fields:
        if f.get("name") == "Status" and f.get("options"):
            opts = {o["name"]: o["id"] for o in f["options"]}
            unmapped = [c for c in columns.values() if c not in opts]
            if unmapped:
                sys.exit(f"ERROR: Status field has no option(s) {', '.join(unmapped)}; edit assets/status-map.json or the board (status-field-missing)")
            return f["id"], opts
    sys.exit("ERROR: the board has no single-select Status field with options (status-field-missing)")


def target_for(kind, obj):
    if kind == "pr":
        if obj.get("state") == "MERGED":
            return "done"
        if obj.get("state") == "CLOSED":
            return None
        return "inProgress" if obj.get("isDraft") else "inReview"
    if obj.get("state", "").upper() == "CLOSED":
        return "done"
    return "inProgress" if obj.get("assignees") else "todo"


def propose(board, smap):
    columns = smap["columns"]
    field_id, options = status_field(board["fields"], columns)
    project_id = board["project"].get("id", "")
    on_board = {}
    for it in board["items"]:
        c = it.get("content") or {}
        if c.get("type") in ("Issue", "PullRequest") and c.get("number") is not None:
            on_board[(("pr" if c["type"] == "PullRequest" else "issue"), c["number"])] = it
    add_steps, status_steps, in_sync = [], [], 0
    universe = [("issue", i) for i in board["issues"]] + [("pr", p) for p in board["prs"]]
    for kind, obj in sorted(universe, key=lambda ko: (ko[0], ko[1]["number"])):
        n = obj["number"]
        target = target_for(kind, obj)
        if target is None:
            continue
        col = columns[target]
        item = on_board.get((kind, n))
        label = f"{'PR' if kind == 'pr' else 'issue'} #{n} ({obj.get('title', '')[:50]})"
        if item is None:
            if (kind == "pr" and obj.get("state") == "MERGED") or (kind == "issue" and obj.get("state", "").upper() == "CLOSED"):
                continue  # never add finished work to the board retroactively
            add_steps.append({"description": f"add {label} to the board, then set Status to {col}", "riskIfFails": "low",
                              "rollback": f"gh project item-delete <project-number> --owner <owner> --id <new-item-id>",
                              "checkpointAfter": True, "action": "add", "kind": kind, "number": n, "url": obj.get("url"),
                              "targetStatus": col, "optionId": options[col]})
        elif (item.get("status") or "") != col:
            prev = item.get("status") or "(none)"
            status_steps.append({"description": f"set Status of {label} from {prev} to {col}", "riskIfFails": "low",
                                 "rollback": f"gh project item-edit --project-id {project_id} --id {item['id']} --field-id {field_id} --single-select-option-id {options.get(prev, '<previous option id>')}",
                                 "checkpointAfter": True, "action": "set-status", "kind": kind, "number": n, "itemId": item["id"],
                                 "fromStatus": prev, "targetStatus": col, "optionId": options[col]})
        else:
            in_sync += 1
    phases = []
    if add_steps:
        phases.append({"name": "add missing items", "steps": add_steps})
    if status_steps:
        phases.append({"name": "set statuses", "steps": status_steps})
    if not phases:
        phases.append({"name": "nothing to do", "steps": [{"description": f"board {board['project'].get('title', '')!r} is in sync: {in_sync} item(s) at their target status", "riskIfFails": "low", "rollback": "none needed: no action is taken", "checkpointAfter": False}]})
    return {"goal": f"Sync board {board['project'].get('title', '')!r} (#{board['project'].get('number', '?')}) with the repository: {len(add_steps)} to add, {len(status_steps)} status change(s), {in_sync} already in sync",
            "phases": phases,
            "facts": {"projectId": project_id, "statusFieldId": field_id, "options": options}}


def main():
    args = sys.argv[1:]
    opts = {"--project": None, "--owner": None, "--board-json-file": None}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or not (opts["--board-json-file"] or (opts["--project"] and opts["--owner"])):
        sys.exit("ERROR: usage: propose_board_sync.py <repo-path> (--project N --owner LOGIN | --board-json-file F)")
    repo = Path(args[0])
    if not repo.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {repo}")
    board = load_fixture(opts["--board-json-file"]) if opts["--board-json-file"] else load_live(repo, opts["--project"], opts["--owner"])
    print(json.dumps(propose(board, load_map()), indent=2))


if __name__ == "__main__":
    main()
