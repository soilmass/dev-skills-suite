#!/usr/bin/env python3
"""Query the OSV.dev API for known vulnerabilities affecting a
normalized dependency list (the output of parse_manifest.py).

Usage:
    osv_batch_query.py <deps.json|->
    osv_batch_query.py <deps.json|-> --frozen-matches-file <matches.json>
    parse_manifest.py <repo> | osv_batch_query.py -

`--frozen-matches-file` is the injectable-fixture flag (SDS-S-065): it
skips every network call and prints the given frozen recording instead,
after verifying that the recording's dependencies are exactly the
input's (ecosystem, name, version) set — a mismatch exits 1 with
`ERROR:` naming it, so a stale recording can never silently stand in
for a different repository. This is what lets a blocking eval row run
the full three-script pipeline offline.

Verified against the live OSV API (https://api.osv.dev) on 2026-09-05:
  POST /v1/querybatch  {"queries": [{"package": {"name","ecosystem"},
                                     "version"}, ...]}
                        -> {"results": [{"vulns": [{"id","modified"}]}]}
  GET  /v1/vulns/{id}   -> full vulnerability record (summary,
                            database_specific.severity, aliases, ...)

querybatch returns only id+modified per hit (by design, for batch
efficiency); full details require a follow-up per-id GET. This script
does both steps.

Dependencies with `version: null` (unresolved) are skipped with a
note on stderr — OSV cannot be queried without a concrete version,
and guessing one would silently produce a wrong audit rather than a
clearly-scoped incomplete one.

Prints a JSON array to stdout: one object per (dependency, vulnerability)
match. An empty array is a valid, complete "no known vulnerabilities
found" result (SDS-C-033), not an error.

Exit code 1, with "ERROR: ..." on stderr, means the OSV API itself was
unreachable or returned an unexpected response — a distinct failure
mode from "queried successfully, found nothing."
"""
import json
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.osv.dev/v1"
BATCH_CHUNK_SIZE = 100  # conservative; OSV's documented batch endpoint
                        # is meant for bulk use but we chunk defensively
                        # rather than assume an unbounded request size.


def _post_json(url, payload, timeout=15):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get_json(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def query_batch(deps):
    """deps: list of {"ecosystem","name","version",...}. Returns list
    of (dep, vuln_id) pairs for every hit, deps with no hits omitted."""
    queryable = [d for d in deps if d.get("version")]
    skipped = [d for d in deps if not d.get("version")]
    for d in skipped:
        print(
            f"NOTE: skipping {d.get('name')!r} ({d.get('ecosystem')}) "
            f"— no resolved version available to query.",
            file=sys.stderr,
        )

    hits = []
    for chunk in _chunks(queryable, BATCH_CHUNK_SIZE):
        payload = {
            "queries": [
                {
                    "package": {"name": d["name"], "ecosystem": d["ecosystem"]},
                    "version": d["version"],
                }
                for d in chunk
            ]
        }
        try:
            resp = _post_json(f"{API_BASE}/querybatch", payload)
        except (urllib.error.URLError, TimeoutError) as e:
            sys.exit(f"ERROR: could not reach OSV API (querybatch): {e}")
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: OSV API returned unparseable JSON (querybatch): {e}")

        results = resp.get("results", [])
        if len(results) != len(chunk):
            sys.exit(
                "ERROR: OSV API returned a different number of results "
                f"({len(results)}) than queries sent ({len(chunk)})."
            )
        for dep, result in zip(chunk, results):
            for vuln in result.get("vulns", []):
                hits.append((dep, vuln["id"]))
    return hits


def fetch_details(vuln_ids):
    """Fetch full records only for the distinct ids actually hit."""
    details = {}
    for vid in sorted(set(vuln_ids)):
        try:
            details[vid] = _get_json(f"{API_BASE}/vulns/{vid}")
        except (urllib.error.URLError, TimeoutError) as e:
            sys.exit(f"ERROR: could not reach OSV API (vulns/{vid}): {e}")
    return details


def _dep_key(d):
    return (d.get("ecosystem"), d.get("name"), d.get("version"))


def frozen_matches(deps, path):
    """Return the frozen recording at `path` iff its dependency set
    equals the input's; otherwise exit 1 naming the mismatch."""
    try:
        matches = json.loads(open(path).read())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load frozen matches file {path}: {e}")
    frozen = {_dep_key(m["dependency"]) for m in matches}
    wanted = {_dep_key(d) for d in deps if d.get("version")}
    if frozen != wanted:
        sys.exit(
            "ERROR: frozen matches file does not cover the input dependencies: "
            f"only-in-input={sorted(wanted - frozen)} only-in-frozen={sorted(frozen - wanted)}"
        )
    return matches


def main():
    args = sys.argv[1:]
    frozen_path = None
    if "--frozen-matches-file" in args:
        i = args.index("--frozen-matches-file")
        if i + 1 >= len(args):
            sys.exit("ERROR: --frozen-matches-file requires a path")
        frozen_path = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: osv_batch_query.py <deps.json|-> [--frozen-matches-file <matches.json>]")
    raw = sys.stdin.read() if args[0] == "-" else open(args[0]).read()
    try:
        deps = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: input is not valid JSON: {e}")

    if frozen_path:
        print(json.dumps(frozen_matches(deps, frozen_path), indent=2))
        return

    hits = query_batch(deps)
    details = fetch_details([vid for _, vid in hits])

    matches = [
        {"dependency": dep, "vuln": details[vid]}
        for dep, vid in hits
    ]
    print(json.dumps(matches, indent=2))


if __name__ == "__main__":
    main()
