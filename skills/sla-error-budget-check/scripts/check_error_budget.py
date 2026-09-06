#!/usr/bin/env python3
"""Decide whether the error budgets allow a release, as a decision-doc
(kit/shapes/decision-doc.schema.json).

Usage:
    check_error_budget.py <openslo.yaml> --measurements-json-file <path> --as-of ISO [--caution-below R]

Requires pyyaml (OpenSLO is YAML). This is the deterministic policy
behind sla-error-budget-check's Analyze stage (SDS-C-060): every
input is a number read from the SLO definitions and the measured
good/total counts, and the mapping to a chosen option is the fixed
rule table below, so it passes the toil test (SDS-S-060).

Inputs (Effect Ladder rung 1 — files are read; nothing is queried):

    <openslo.yaml>   OpenSLO v1 documents (kind: SLO), one or more in
                     the file; each needs metadata.name, spec.objectives
                     [0].target in (0, 1), and spec.timeWindow[0].duration
                     such as "30d" or "28d".
    --measurements-json-file
                     {"slos": {"<name>": {"windows": {"<duration>":
                     {"good": N, "total": M}, "1h": {...}, "6h": {...}}}}}
                     — the good and total event counts per SLO for the
                     SLO's own window and, optionally, the 1h and 6h
                     burn-rate windows. How the counts are obtained
                     (a Prometheus query, a vendor export) is outside
                     this script; the file is the injectable fixture
                     (SDS-S-065).
    --as-of          the clock (SDS-S-064), recorded in the decision.

Per SLO, with budget = 1 - target and error = 1 - good/total:
    consumed  = error / budget over the SLO window
    remaining = 1 - consumed
    burn rate = error_w / budget for a short window w

Rule table (first match wins), states per SLO then the decision:
    no measurement, or total 0, for the SLO window  -> no-data
    remaining <= 0                                  -> exhausted
    1h burn rate >= 14.4, or 6h burn rate >= 6      -> burning (the
                                                       multiwindow fast-
                                                       and slow-burn
                                                       thresholds)
    remaining < --caution-below (default 0.25)      -> low
    otherwise                                       -> healthy

    any SLO exhausted or burning                    -> freeze
    any SLO low or no-data                          -> caution
    every SLO healthy                               -> proceed
    no SLO documents                                -> no-slos

Prints one decision-doc; a file with no SLO documents yields
`no-slos` with empty drivers (SDS-C-033). Exit 1 with "ERROR: ..." on
stderr for an SLO file that is missing or not YAML (slo-unparseable),
an SLO document without a name, a target in (0, 1), or a window
(slo-invalid), a measurements file that is not the expected shape
(measurements-unparseable), or a missing or malformed --as-of
(as-of-invalid).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("ERROR: pyyaml is required (pip install pyyaml)")

OPTIONS = ["proceed", "caution", "freeze", "no-slos"]
FAST_BURN_1H, SLOW_BURN_6H = 14.4, 6.0


def parse_ts(s, what):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        sys.exit(f"ERROR: {what} is not an ISO-8601 timestamp (as-of-invalid): {s!r}")


def load_slos(path):
    p = Path(path)
    if not p.is_file():
        sys.exit(f"ERROR: SLO file is missing (slo-unparseable): {path}")
    try:
        docs = [d for d in yaml.safe_load_all(p.read_text(encoding="utf-8")) if d]
    except yaml.YAMLError as e:
        sys.exit(f"ERROR: {path} is not valid YAML (slo-unparseable): {e}")
    slos = []
    for d in docs:
        if not isinstance(d, dict) or d.get("kind") != "SLO":
            continue
        name = (d.get("metadata") or {}).get("name")
        spec = d.get("spec") or {}
        objectives = spec.get("objectives") or []
        windows = spec.get("timeWindow") or []
        target = (objectives[0] if objectives and isinstance(objectives[0], dict) else {}).get("target")
        duration = (windows[0] if windows and isinstance(windows[0], dict) else {}).get("duration")
        if not name or not isinstance(target, (int, float)) or not 0 < target < 1 or not duration:
            sys.exit(f"ERROR: SLO {name or '<unnamed>'} needs metadata.name, objectives[0].target in (0, 1), and timeWindow[0].duration (slo-invalid)")
        slos.append({"name": name, "target": float(target), "window": str(duration), "description": spec.get("description", "")})
    return slos


def load_measurements(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load measurements {path} (measurements-unparseable): {e}")
    if not isinstance(data, dict) or not isinstance(data.get("slos"), dict):
        sys.exit(f"ERROR: measurements {path} must be an object with an slos object (measurements-unparseable)")
    return data["slos"]


def ratio(w):
    if not isinstance(w, dict):
        return None
    good, total = w.get("good"), w.get("total")
    if not isinstance(good, (int, float)) or not isinstance(total, (int, float)) or total <= 0:
        return None
    return 1 - good / total


def assess(slo, m, caution_below):
    budget = 1 - slo["target"]
    windows = (m or {}).get("windows") or {}
    err = ratio(windows.get(slo["window"]))
    if err is None:
        return {"state": "no-data", "remaining": None, "burn1h": None, "burn6h": None}
    remaining = 1 - err / budget
    e1, e6 = ratio(windows.get("1h")), ratio(windows.get("6h"))
    b1 = e1 / budget if e1 is not None else None
    b6 = e6 / budget if e6 is not None else None
    if remaining <= 0:
        state = "exhausted"
    elif (b1 is not None and b1 >= FAST_BURN_1H) or (b6 is not None and b6 >= SLOW_BURN_6H):
        state = "burning"
    elif remaining < caution_below:
        state = "low"
    else:
        state = "healthy"
    return {"state": state, "remaining": remaining, "burn1h": b1, "burn6h": b6, "sli": 1 - err}


def fmt(x, pct=False):
    if x is None:
        return "n/a"
    return f"{x:.1%}" if pct else f"{x:.1f}x"


def main():
    args = sys.argv[1:]
    opts = {"--measurements-json-file": None, "--as-of": None, "--caution-below": "0.25"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or not opts["--measurements-json-file"]:
        sys.exit("ERROR: usage: check_error_budget.py <openslo.yaml> --measurements-json-file F --as-of ISO [--caution-below R]")
    if not opts["--as-of"]:
        sys.exit("ERROR: --as-of is required (as-of-invalid)")
    as_of = parse_ts(opts["--as-of"], "--as-of")
    try:
        caution_below = float(opts["--caution-below"])
        assert 0 <= caution_below <= 1
    except (ValueError, AssertionError):
        sys.exit(f"ERROR: --caution-below must be a ratio in [0, 1] (as-of-invalid): {opts['--caution-below']!r}")
    slos = load_slos(args[0])
    measurements = load_measurements(opts["--measurements-json-file"])
    drivers, negative, positive, states = [], [], [], {}
    for slo in slos:
        a = assess(slo, measurements.get(slo["name"]), caution_below)
        states[slo["name"]] = a["state"]
        if a["state"] == "no-data":
            line = f"{slo['name']} ({slo['target']:.3%} over {slo['window']}): no-data — no measurement for the {slo['window']} window"
        else:
            line = (f"{slo['name']} ({slo['target']:.3%} over {slo['window']}): {a['state']} — SLI {a['sli']:.4%}, budget remaining {fmt(a['remaining'], True)}, "
                    f"burn rate 1h {fmt(a['burn1h'])} / 6h {fmt(a['burn6h'])}")
        drivers.append(line)
        (positive if a["state"] == "healthy" else negative).append(line)
    if not slos:
        chosen, why = "no-slos", "the file defines no SLO documents; there is no error budget to check"
    elif any(s in ("exhausted", "burning") for s in states.values()):
        bad = [n for n, s in states.items() if s in ("exhausted", "burning")]
        chosen, why = "freeze", f"{', '.join(bad)} {'is' if len(bad) == 1 else 'are'} {' / '.join(sorted({states[n] for n in bad}))}; the budget policy stops feature releases until the burn is under the threshold"
    elif any(s in ("low", "no-data") for s in states.values()):
        bad = [n for n, s in states.items() if s in ("low", "no-data")]
        chosen, why = "caution", f"{', '.join(bad)} {'is' if len(bad) == 1 else 'are'} {' / '.join(sorted({states[n] for n in bad}))}; release with a rollback plan and watch the burn rate"
    else:
        chosen, why = "proceed", f"every SLO ({len(slos)}) is healthy with budget remaining above {caution_below:.0%}"
    print(json.dumps({
        "status": "accepted",
        "contextAndProblemStatement": f"Do the error budgets allow a release as of {as_of.isoformat().replace('+00:00', 'Z')}? {len(slos)} SLO(s) defined; states: {', '.join(f'{n}={s}' for n, s in states.items()) or 'none'}.",
        "decisionDrivers": drivers,
        "consideredOptions": OPTIONS,
        "decisionOutcome": {"chosenOption": chosen, "justification": why},
        "consequences": {"positive": positive, "negative": negative},
        "confirmation": "Re-run this check immediately before releasing; burn rates move by the hour. Multiwindow thresholds: 1h burn >= 14.4x or 6h burn >= 6x.",
    }, indent=2))


if __name__ == "__main__":
    main()
