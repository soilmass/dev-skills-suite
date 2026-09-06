#!/usr/bin/env python3
"""Review a Terraform plan (JSON) for the changes that lose data, expose
resources, or weaken protection, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    review_plan.py <plan.json> [--stateful <types.json>]

Input: the output of `terraform show -json <planfile>` — an object
with `format_version` and `resource_changes`, each carrying
`address`, `type`, and `change.actions` (create, update, delete,
no-op, or the replace pair delete+create / create+delete) with
`before` and `after` attribute maps. OpenTofu emits the same shape.
Effect Ladder rung 1 (SDS-S-060): the file is read; no provider or
state is contacted, and the plan is never applied.

Rules emitted (per resource change):

    tf/destroy               actions is delete alone -> error (the
                             resource and whatever it holds are gone)
    tf/replace-stateful      a replace (delete+create) of a type in the
                             stateful list (assets/stateful-types.json:
                             databases, buckets, volumes, queues, key
                             vaults, …) -> error (a replace destroys the
                             data; a create_before_destroy does not save
                             it)
    tf/replace               a replace of any other type -> warning
                             (downtime for the resource's users)
    tf/public-exposure       `after` opens the world: an ingress rule
                             with 0.0.0.0/0 or ::/0, publicly_accessible
                             true, acl public-read, block_public_*
                             false, allow_blob_public_access true ->
                             warning
    tf/encryption-off        `after` sets encrypted, storage_encrypted,
                             encrypt, or kms_key_id-bearing encryption
                             to false/absent where `before` had it, or
                             creates a stateful resource with it false
                             -> warning
    tf/deletion-protection-off a stateful resource created or updated
                             with deletion_protection false (or
                             force_destroy true) -> info
    tf/large-update          more than --large (default 25) resources
                             change in one plan -> info on the plan

`tool.properties` counts create, update, delete, replace, and no-op.
Whether a destroy is intended (a decommission) and whether a
replacement is survivable (a snapshot exists) is the skill's Analyze
stage (SDS-S-061).

Prints one finding-list; a plan of creates and safe updates yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a file that cannot be read or parsed (plan-unparseable), one
without `resource_changes` (plan-invalid), or a stateful list that is
not a JSON array (stateful-invalid).
"""
import json
import sys
from pathlib import Path

WORLD = {"0.0.0.0/0", "::/0"}
ENC_KEYS = ("encrypted", "storage_encrypted", "encrypt", "server_side_encryption_configuration", "encryption_at_rest_enabled")


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}], "properties": props}


def walk_values(obj):
    """Yield every scalar in a nested structure."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_values(v)
    else:
        yield obj


def exposes(after):
    if not isinstance(after, dict):
        return None
    if after.get("publicly_accessible") is True:
        return "publicly_accessible = true"
    if after.get("acl") in ("public-read", "public-read-write"):
        return f"acl = {after['acl']}"
    if after.get("allow_blob_public_access") is True:
        return "allow_blob_public_access = true"
    for k in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
        if after.get(k) is False:
            return f"{k} = false"
    for rule in (after.get("ingress") or []) + ([after] if after.get("cidr_blocks") or after.get("cidr_ipv4") else []):
        if isinstance(rule, dict):
            cidrs = set(rule.get("cidr_blocks") or []) | set(rule.get("ipv6_cidr_blocks") or []) | ({rule["cidr_ipv4"]} if rule.get("cidr_ipv4") else set())
            if cidrs & WORLD:
                return f"ingress from {', '.join(sorted(cidrs & WORLD))} on port {rule.get('from_port', rule.get('port', '?'))}"
    return None


def encryption_off(before, after, stateful):
    if not isinstance(after, dict):
        return None
    for k in ENC_KEYS:
        if k in after:
            if after[k] is False and (before or {}).get(k) not in (False, None):
                return f"{k} switched from true to false"
            if after[k] is False and stateful and not before:
                return f"created with {k} = false"
            if after[k] is None and isinstance((before or {}).get(k), (dict, list)) and (before or {}).get(k):
                return f"{k} removed"
    return None


def main():
    args = sys.argv[1:]
    opts = {"--stateful": None, "--large": "25"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: review_plan.py <plan.json> [--stateful <types.json>] [--large N]")
    path = Path(args[0])
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not read {path} (plan-unparseable): {e}")
    if not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list):
        sys.exit(f"ERROR: {path} is not terraform show -json output with resource_changes (plan-invalid)")
    sp = opts["--stateful"] or str(Path(__file__).resolve().parent.parent / "assets" / "stateful-types.json")
    try:
        stateful = set(json.loads(Path(sp).read_text(encoding="utf-8"))["statefulTypes"])
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: stateful list {sp} must be {{statefulTypes: [types]}} (stateful-invalid): {e}")
    try:
        large = int(opts["--large"])
    except ValueError:
        sys.exit("ERROR: --large must be an integer (stateful-invalid)")
    uri = path.name
    out, counts = [], {"create": 0, "update": 0, "delete": 0, "replace": 0, "no-op": 0}
    for rc in plan["resource_changes"]:
        addr, rtype = rc.get("address", "?"), rc.get("type", "")
        ch = rc.get("change") or {}
        actions = ch.get("actions") or []
        before, after = ch.get("before"), ch.get("after")
        is_stateful = rtype in stateful
        props = {"address": addr, "type": rtype, "actions": actions}
        if actions == ["delete"]:
            counts["delete"] += 1
            out.append(finding("tf/destroy", "error", f"{addr} will be destroyed" + ("; it is a stateful resource" if is_stateful else ""), uri, {**props, "stateful": is_stateful}))
            continue
        if set(actions) == {"delete", "create"}:
            counts["replace"] += 1
            if is_stateful:
                out.append(finding("tf/replace-stateful", "error", f"{addr} ({rtype}) will be replaced; a replace destroys the data it holds", uri, {**props, "stateful": True}))
            else:
                out.append(finding("tf/replace", "warning", f"{addr} ({rtype}) will be replaced; its users see downtime", uri, props))
        elif actions == ["create"]:
            counts["create"] += 1
        elif actions == ["update"]:
            counts["update"] += 1
        else:
            counts["no-op"] += 1
            continue
        exp = exposes(after)
        if exp:
            out.append(finding("tf/public-exposure", "warning", f"{addr}: {exp}", uri, {**props, "exposure": exp}))
        enc = encryption_off(before, after, is_stateful)
        if enc:
            out.append(finding("tf/encryption-off", "warning", f"{addr}: {enc}", uri, {**props, "encryption": enc}))
        if is_stateful and isinstance(after, dict) and (after.get("deletion_protection") is False or after.get("force_destroy") is True):
            out.append(finding("tf/deletion-protection-off", "info", f"{addr}: deletion protection is off (deletion_protection false / force_destroy true)", uri, props))
    changing = counts["create"] + counts["update"] + counts["delete"] + counts["replace"]
    if changing > large:
        out.append(finding("tf/large-update", "info", f"{changing} resources change in one plan (limit {large}); apply in slices", uri, {"changing": changing, "limit": large}))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order[r["level"]], r["properties"].get("address", ""), r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "terraform-plan-review", "version": "0.1.0"},
                                         "properties": {"formatVersion": plan.get("format_version"), "terraformVersion": plan.get("terraform_version"), "counts": counts,
                                                        "destructive": sum(1 for r in out if r["level"] == "error")}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
