#!/usr/bin/env python3
"""Review a PostgreSQL EXPLAIN (FORMAT JSON) plan for the shapes that
make queries slow, as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    review_plan.py <plan.json> [--large-rows N]

Input: the output of `EXPLAIN (FORMAT JSON) <query>` or
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>` — a one-element
array whose element has a "Plan" tree. With ANALYZE the plan carries
actual rows and timings, and the estimate and spill rules below
become available; without it only the structural rules fire.
Effect Ladder rung 1 (SDS-S-060): the file is read; no database is
contacted.

Rules emitted (over every node in the tree):

    plan/seq-scan-large        a Seq Scan whose Plan Rows (or Actual
                               Rows) is >= --large-rows (default
                               10000), with a Filter -> warning: a
                               predicate over a large table with no
                               index to use
    plan/nested-loop-large     a Nested Loop whose outer child yields
                               >= --large-rows rows and whose inner
                               child is a Seq Scan -> warning: the
                               inner scan repeats per outer row
    plan/estimate-off          with ANALYZE: Actual Rows and Plan Rows
                               differ by 10x or more on a node with
                               >= 1000 actual rows -> warning: the
                               planner chose on wrong statistics
                               (ANALYZE the table, or extend statistics)
    plan/sort-on-disk          with ANALYZE: a Sort whose Sort Space
                               Type is Disk -> warning: work_mem is
                               below the sort's need
    plan/hash-batches          with ANALYZE: a Hash node with Hash
                               Batches > 1 -> info: the hash table
                               spilled
    plan/heap-fetches          an Index Only Scan with Heap Fetches
                               greater than Actual Rows / 2 -> info:
                               the visibility map is stale; VACUUM
    plan/lossy-bitmap          a Bitmap Heap Scan with Lossy Heap
                               Blocks > 0 -> info: work_mem too small
                               for an exact bitmap

Every finding is located at the node's path in the tree
(Plan/Plans[1]/Plans[0]) in `properties.nodePath`, with the node
type, relation, and the numbers. Whether a slow shape matters — the
query runs nightly, the table is small in production — is the
skill's Analyze stage (SDS-S-061).

Prints one finding-list; a plan with none of these shapes yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a file that does not parse or is not an EXPLAIN JSON array with a
Plan (plan-unparseable), or a --large-rows that is not a positive
integer (threshold-invalid).
"""
import json
import sys
from pathlib import Path


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}],
            "properties": props}


def walk(node, path="Plan"):
    yield path, node
    for i, child in enumerate(node.get("Plans") or []):
        yield from walk(child, f"{path}/Plans[{i}]")


def rows(node):
    return node.get("Actual Rows", node.get("Plan Rows", 0)) or 0


def main():
    args = sys.argv[1:]
    large = 10000
    if "--large-rows" in args:
        i = args.index("--large-rows")
        if i + 1 >= len(args):
            sys.exit("ERROR: --large-rows requires a value")
        try:
            large = int(args[i + 1])
        except ValueError:
            sys.exit("ERROR: --large-rows must be an integer (threshold-invalid)")
        if large < 1:
            sys.exit("ERROR: --large-rows must be positive (threshold-invalid)")
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: review_plan.py <plan.json> [--large-rows N]")
    path = Path(args[0])
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load {path} (plan-unparseable): {e}")
    if isinstance(doc, dict) and "Plan" in doc:
        doc = [doc]
    if not (isinstance(doc, list) and doc and isinstance(doc[0], dict) and isinstance(doc[0].get("Plan"), dict)):
        sys.exit(f"ERROR: {path} is not EXPLAIN (FORMAT JSON) output: expected [{{\"Plan\": {{...}}}}] (plan-unparseable)")
    root = doc[0]["Plan"]
    analyzed = "Actual Rows" in root
    uri = path.name
    results = []
    for npath, n in walk(root):
        t = n.get("Node Type", "")
        rel = n.get("Relation Name") or n.get("Alias") or ""
        base = {"nodePath": npath, "nodeType": t, "relation": rel}
        if t == "Seq Scan" and n.get("Filter") and rows(n) >= large:
            results.append(finding("plan/seq-scan-large", "warning",
                                   f"Seq Scan on {rel} over {rows(n)} rows with filter {n['Filter'][:60]}; no index serves this predicate",
                                   uri, {**base, "rows": rows(n), "filter": n["Filter"][:200], "removedByFilter": n.get("Rows Removed by Filter")}))
        if t == "Nested Loop" and len(n.get("Plans") or []) == 2:
            outer, inner = n["Plans"]
            if rows(outer) >= large and inner.get("Node Type") == "Seq Scan":
                results.append(finding("plan/nested-loop-large", "warning",
                                       f"Nested Loop runs a Seq Scan on {inner.get('Relation Name', '')} once per {rows(outer)} outer rows",
                                       uri, {**base, "outerRows": rows(outer), "innerRelation": inner.get("Relation Name", ""), "loops": inner.get("Actual Loops")}))
        if analyzed and "Actual Rows" in n and "Plan Rows" in n:
            a, p = n["Actual Rows"], n["Plan Rows"]
            if a >= 1000 and p > 0 and (a / p >= 10 or p / a >= 10):
                results.append(finding("plan/estimate-off", "warning",
                                       f"{t} on {rel or npath}: planned {p} rows, got {a} ({a / p:.0f}x); the planner chose on wrong statistics",
                                       uri, {**base, "planRows": p, "actualRows": a, "ratio": round(a / p, 1)}))
        if t == "Sort" and n.get("Sort Space Type") == "Disk":
            results.append(finding("plan/sort-on-disk", "warning",
                                   f"Sort on {n.get('Sort Key')} spilled to disk ({n.get('Sort Space Used')} kB); work_mem is below the sort's need",
                                   uri, {**base, "sortKey": n.get("Sort Key"), "spaceUsedKb": n.get("Sort Space Used")}))
        if t == "Hash" and (n.get("Hash Batches") or 1) > 1:
            results.append(finding("plan/hash-batches", "info",
                                   f"Hash built in {n['Hash Batches']} batches; the hash table spilled",
                                   uri, {**base, "batches": n["Hash Batches"], "peakMemoryKb": n.get("Peak Memory Usage")}))
        if t == "Index Only Scan" and (n.get("Heap Fetches") or 0) > max(rows(n), 1) / 2:
            results.append(finding("plan/heap-fetches", "info",
                                   f"Index Only Scan on {rel} fetched {n['Heap Fetches']} heap tuples for {rows(n)} rows; the visibility map is stale — VACUUM",
                                   uri, {**base, "heapFetches": n["Heap Fetches"], "rows": rows(n)}))
        if t == "Bitmap Heap Scan" and (n.get("Lossy Heap Blocks") or 0) > 0:
            results.append(finding("plan/lossy-bitmap", "info",
                                   f"Bitmap Heap Scan on {rel} used {n['Lossy Heap Blocks']} lossy blocks; work_mem is too small for an exact bitmap",
                                   uri, {**base, "lossyBlocks": n["Lossy Heap Blocks"]}))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["properties"]["nodePath"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "query-plan-review", "version": "0.1.0"},
                                         "properties": {"analyzed": analyzed, "nodes": sum(1 for _ in walk(root)), "totalCost": root.get("Total Cost"),
                                                        "executionTimeMs": doc[0].get("Execution Time")}},
                                "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
