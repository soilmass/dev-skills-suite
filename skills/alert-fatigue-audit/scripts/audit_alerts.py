#!/usr/bin/env python3
"""Find the alerts that page people without telling them anything, as a
finding-list (kit/shapes/finding-list.schema.json).

Usage:
    audit_alerts.py <alerts.json> --as-of ISO [--rules <rules.yml>] [--window-days N]

Inputs (standards-first, SDS-C-030):
    alerts.json  an array of alerts in the Alertmanager API v2 shape:
                 {labels: {alertname, severity, ...}, annotations:
                 {runbook_url?, summary?}, startsAt, endsAt, status:
                 {state: active|resolved|suppressed}, acknowledged?}
                 — an export of alert history, one entry per firing.
                 `acknowledged` (bool) is the one extension: whether a
                 human acted on the page.
    rules.yml    optional Prometheus alerting-rules file; when given,
                 rules with no `runbook_url` annotation and rules that
                 never fired in the window are reported. Requires
                 PyYAML.
`--as-of` injects the clock (SDS-S-064) and is REQUIRED: open alerts
have no endsAt, and "how long has this been firing" depends on now.

Effect Ladder rung 1 (SDS-S-060): files only. The judgment — whether
a noisy alert should be deleted, re-thresholded, or routed to a
dashboard — is the skill's Analyze stage (SDS-S-061).

Rule table (per alertname, over --window-days, default 30):
    alert/never-acknowledged  fired >= 5 times, acknowledged 0 times
                              -> warning (nobody acts on it; it is
                              noise by definition)
    alert/flapping            fired >= 10 times with a median duration
                              under 5 minutes -> warning (the threshold
                              sits on the signal's natural variance)
    alert/always-firing       an active alert open for over 7 days
                              -> warning (a standing condition, not an
                              event)
    alert/no-runbook          fired at least once and its annotations
                              (or its rule) carry no runbook_url
                              -> info
    alert/co-firing           two alertnames whose firings overlap in
                              >= 90% of the more frequent one's
                              firings (>= 5 firings) -> info (one of
                              them is redundant, or both are symptoms
                              of one cause)
    alert/silent-rule         with --rules: a rule that never fired in
                              the window -> info (dead, or the window
                              is too short to know)

Prints one finding-list; a quiet, well-run alert set yields an empty
`results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a
history file that is not an array of alerts with labels.alertname and
startsAt (alerts-unparseable), a rules file that does not parse
(rules-unparseable), or a missing/invalid --as-of (as-of-invalid).
"""
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}],
            "properties": props}


def parse_ts(value, what):
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        sys.exit(f"ERROR: {what} {value!r} is not an ISO-8601 timestamp (as-of-invalid)")
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def load_alerts(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: could not load {path} (alerts-unparseable): {e}")
    if not isinstance(data, list) or not all(isinstance(a, dict) and isinstance(a.get("labels"), dict) and a["labels"].get("alertname") and a.get("startsAt") for a in data):
        sys.exit(f"ERROR: {path} must be an array of alerts each with labels.alertname and startsAt (alerts-unparseable)")
    return data


def load_rules(path):
    try:
        import yaml
    except ImportError:
        sys.exit("ERROR: PyYAML is required for --rules (pip install pyyaml)")
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        rules = [r for g in doc["groups"] for r in g.get("rules", []) if "alert" in r]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as e:
        sys.exit(f"ERROR: could not load rules {path} (rules-unparseable): {e}")
    return {r["alert"]: r for r in rules}


def main():
    args = sys.argv[1:]
    opts = {"--as-of": None, "--rules": None, "--window-days": "30"}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: audit_alerts.py <alerts.json> --as-of ISO [--rules <rules.yml>] [--window-days N]")
    if not opts["--as-of"]:
        sys.exit("ERROR: --as-of is required; open alerts and the window depend on the clock (as-of-invalid)")
    as_of = parse_ts(opts["--as-of"], "--as-of")
    try:
        window = timedelta(days=int(opts["--window-days"]))
    except ValueError:
        sys.exit("ERROR: --window-days must be an integer (as-of-invalid)")
    alerts = load_alerts(args[0])
    rules = load_rules(opts["--rules"]) if opts["--rules"] else None
    uri = Path(args[0]).name

    by_name = defaultdict(list)
    for a in alerts:
        start = parse_ts(a["startsAt"], "startsAt")
        if start < as_of - window:
            continue
        end = parse_ts(a["endsAt"], "endsAt") if a.get("endsAt") else None
        active = (a.get("status") or {}).get("state") == "active" or end is None
        by_name[a["labels"]["alertname"]].append({"start": start, "end": None if active else end, "ack": bool(a.get("acknowledged")),
                                                  "runbook": bool((a.get("annotations") or {}).get("runbook_url")),
                                                  "severity": a["labels"].get("severity", "")})
    results = []
    for name, fs in sorted(by_name.items()):
        n = len(fs)
        acks = sum(f["ack"] for f in fs)
        durations = [((f["end"] or as_of) - f["start"]).total_seconds() / 60 for f in fs]
        med = statistics.median(durations) if durations else 0
        sev = fs[0]["severity"]
        if n >= 5 and acks == 0:
            results.append(finding("alert/never-acknowledged", "warning",
                                   f"{name} fired {n} times in {window.days} days and was never acknowledged; nobody acts on it",
                                   uri, {"alertname": name, "firings": n, "acknowledged": 0, "severity": sev}))
        if n >= 10 and med < 5:
            results.append(finding("alert/flapping", "warning",
                                   f"{name} fired {n} times with a median duration of {med:.1f} minutes; the threshold sits on the signal's noise",
                                   uri, {"alertname": name, "firings": n, "medianMinutes": round(med, 1), "severity": sev}))
        open_ = [f for f in fs if f["end"] is None]
        for f in open_:
            days = (as_of - f["start"]).days
            if days > 7:
                results.append(finding("alert/always-firing", "warning",
                                       f"{name} has been firing for {days} days; a standing condition is not an event",
                                       uri, {"alertname": name, "openDays": days, "severity": sev}))
                break
        has_runbook = any(f["runbook"] for f in fs) or (rules is not None and name in rules and bool((rules[name].get("annotations") or {}).get("runbook_url")))
        if not has_runbook:
            results.append(finding("alert/no-runbook", "info",
                                   f"{name} fired {n} time(s) and carries no runbook_url; the responder starts from nothing",
                                   uri, {"alertname": name, "firings": n, "severity": sev}))
    names = sorted(by_name)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            fa, fb = by_name[a], by_name[b]
            more, less, mname, lname = (fa, fb, a, b) if len(fa) >= len(fb) else (fb, fa, b, a)
            if len(more) < 5:
                continue
            overlapping = sum(1 for x in more if any(x["start"] <= (y["end"] or as_of) and y["start"] <= (x["end"] or as_of) for y in less))
            ratio = overlapping / len(more)
            if ratio >= 0.9:
                results.append(finding("alert/co-firing", "info",
                                       f"{lname} fires alongside {mname} in {ratio:.0%} of {mname}'s {len(more)} firings; one is redundant or both are symptoms of one cause",
                                       uri, {"alertnames": [mname, lname], "overlapRatio": round(ratio, 2), "firings": len(more)}))
    if rules is not None:
        for name in sorted(rules):
            if name not in by_name:
                results.append(finding("alert/silent-rule", "info",
                                       f"rule {name} never fired in the last {window.days} days; dead, or the window is too short to know",
                                       Path(opts["--rules"]).name, {"alertname": name, "windowDays": window.days}))
    order = {"warning": 0, "info": 1}
    results.sort(key=lambda r: (order[r["level"]], r["ruleId"], json.dumps(r["properties"], sort_keys=True)))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "alert-fatigue-audit", "version": "0.1.0"},
                                         "properties": {"asOf": as_of.isoformat(), "windowDays": window.days, "alertnames": len(by_name), "firings": sum(len(v) for v in by_name.values())}},
                                "results": results}]}, indent=2))


if __name__ == "__main__":
    main()
