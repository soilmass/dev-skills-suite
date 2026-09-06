#!/usr/bin/env python3
"""Scan test data — fixtures, seeds, factories, recorded responses —
for values that look like real personal data, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    scan_test_data.py <repo-path> [--paths dir,dir] [--allowlist <allowlist.json>] [--exclude dir,dir]

Effect Ladder rung 1 (SDS-S-060): files are read; nothing is run and
nothing leaves the machine. By default the scan covers the directories
that conventionally hold test data (test, tests, spec, __tests__,
fixtures, testdata, seeds, seed, factories, mocks, cassettes,
snapshots, __snapshots__, e2e) plus files named *.fixture.*, *.seed.*,
and *.cassette.*; `--paths` replaces that with explicit directories
(relative to the repository). Text files up to 2 MiB are scanned;
binary files are skipped and counted.

Detectors (each with a validity check so random digits do not fire):

    pii/credit-card   13-19 digit groups that pass Luhn and are not a
                      known test card number -> error
    pii/ssn           US Social Security Number in AAA-GG-SSSS form with
                      a valid area/group/serial -> error
    pii/iban          IBAN whose mod-97 checksum holds -> error
    pii/email         an address whose domain is not a reserved or
                      allowlisted test domain (example.com, *.test,
                      *.invalid, *.localhost, *.example) -> warning
    pii/phone         an E.164 or NANP number outside the fictional
                      555-01xx range -> warning
    pii/ip-address    a public IPv4 address (not private, loopback,
                      link-local, or the documentation ranges) -> info
    pii/date-of-birth a key named like dob/birth_date/date_of_birth with
                      an ISO date value -> info

The allowlist (`assets/allowlist.json` by default) carries the safe
e-mail domains, the known test card numbers, and literal values to
ignore; `--allowlist` swaps it for the team's own. Whether a hit is a
real person's data or a plausible-looking invention is the skill's
Analyze stage (SDS-S-061) — the script reports what validates.

`tool.properties` carries the directories scanned, the file counts,
and hits per rule. Prints one finding-list; clean test data yields an
empty `results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr
for a path that is not a directory (repo-invalid), an explicit
`--paths` entry that does not exist (paths-missing), or an allowlist
that is not the expected shape (allowlist-invalid).
"""
import ipaddress
import json
import re
import sys
from collections import Counter
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".skills-state", ".venv", "venv"}
DEFAULT_DIRS = {"test", "tests", "spec", "__tests__", "fixtures", "testdata", "seeds", "seed", "factories", "mocks", "cassettes", "snapshots", "__snapshots__", "e2e"}
FILE_MARKERS = (".fixture.", ".seed.", ".cassette.")
MAX_BYTES = 2 * 1024 * 1024

CARD_RE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
SSN_RE = re.compile(r"(?<![\d-])(\d{3})-(\d{2})-(\d{4})(?![\d-])")
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b")
EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
PHONE_RE = re.compile(r"(?<![\w.-])(\+\d{1,3}[ .-]?)?\(?(\d{3})\)?[ .-]?(\d{3})[ .-]?(\d{4})(?![\w-])")
IPV4_RE = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.])")
DOB_RE = re.compile(r"""(?i)\b(dob|date_of_birth|dateofbirth|birth_?date|birthday)\b["']?\s*[:=]\s*["']?(\d{4}-\d{2}-\d{2})""")


def finding(rule, level, text, uri, line, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
            "properties": props}


def luhn_ok(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def iban_ok(s):
    body = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in body)
    return int(num) % 97 == 1


def ssn_ok(a, g, s):
    a, g, s = int(a), int(g), int(s)
    return a not in (0, 666) and a < 900 and g != 0 and s != 0


def mask(s):
    digits = re.sub(r"\D", "", s)
    return "*" * max(0, len(digits) - 4) + digits[-4:]


def scan_text(text, rel, allow):
    hits = []
    safe_domains = allow["safeEmailDomains"]
    for ln, line in enumerate(text.splitlines(), 1):
        if any(v in line for v in allow["ignoreValues"]):
            continue
        for m in CARD_RE.finditer(line):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and luhn_ok(digits) and digits not in allow["testCardNumbers"] and len(set(digits)) > 1:
                hits.append(finding("pii/credit-card", "error", f"Luhn-valid card number {mask(digits)} in test data", rel, ln, {"value": mask(digits), "length": len(digits)}))
        for m in SSN_RE.finditer(line):
            if ssn_ok(*m.groups()):
                hits.append(finding("pii/ssn", "error", f"US SSN ***-**-{m.group(3)} in test data", rel, ln, {"value": f"***-**-{m.group(3)}"}))
        for m in IBAN_RE.finditer(line):
            if iban_ok(m.group(1)):
                hits.append(finding("pii/iban", "error", f"checksum-valid IBAN {m.group(1)[:4]}…{m.group(1)[-4:]} in test data", rel, ln, {"value": m.group(1)[:4] + "…" + m.group(1)[-4:], "country": m.group(1)[:2]}))
        for m in EMAIL_RE.finditer(line):
            dom = m.group(1).lower()
            tld = dom.rsplit(".", 1)[-1]
            if dom in safe_domains or tld in ("test", "invalid", "localhost", "example") or any(dom.endswith("." + d) for d in safe_domains):
                continue
            local = m.group(0).split("@")[0]
            hits.append(finding("pii/email", "warning", f"e-mail address at a real domain ({dom}) in test data", rel, ln, {"domain": dom, "value": f"{local[:1]}***@{dom}"}))
        for m in PHONE_RE.finditer(line):
            cc, area, exch, last = m.groups()
            if exch == "555" and last.startswith("01"):
                continue
            if not cc and (area[0] in "01" or exch[0] in "01"):
                continue
            hits.append(finding("pii/phone", "warning", f"phone number ending {last} in test data (outside the 555-01xx fictional range)", rel, ln, {"value": f"***-***-{last}", "countryCode": (cc or "").strip(" .-") or None}))
        for m in IPV4_RE.finditer(line):
            try:
                ip = ipaddress.ip_address(m.group(1))
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified or any(ip in ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")):
                continue
            hits.append(finding("pii/ip-address", "info", f"public IP address {ip} in test data", rel, ln, {"value": str(ip)}))
        for m in DOB_RE.finditer(line):
            hits.append(finding("pii/date-of-birth", "info", f"{m.group(1)} with a full date ({m.group(2)}) in test data", rel, ln, {"key": m.group(1), "value": m.group(2)}))
    return hits


def main():
    args = sys.argv[1:]
    opts = {"--paths": None, "--allowlist": None, "--exclude": ""}
    for flag in list(opts):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        sys.exit("ERROR: usage: scan_test_data.py <repo-path> [--paths dir,dir] [--allowlist F] [--exclude dir,dir]")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    ap = opts["--allowlist"] or str(Path(__file__).resolve().parent.parent / "assets" / "allowlist.json")
    try:
        allow = json.loads(Path(ap).read_text(encoding="utf-8"))
        assert isinstance(allow, dict)
        allow = {"safeEmailDomains": {d.lower() for d in allow.get("safeEmailDomains", [])},
                 "testCardNumbers": {re.sub(r"\D", "", str(n)) for n in allow.get("testCardNumbers", [])},
                 "ignoreValues": [str(v) for v in allow.get("ignoreValues", [])]}
    except Exception as e:  # noqa: BLE001
        sys.exit(f"ERROR: allowlist {ap} must be a JSON object with safeEmailDomains/testCardNumbers/ignoreValues lists (allowlist-invalid): {e}")
    exclude = {x.strip() for x in opts["--exclude"].split(",") if x.strip()}
    if opts["--paths"]:
        dirs = []
        for d in opts["--paths"].split(","):
            d = d.strip()
            if d and not (root / d).is_dir():
                sys.exit(f"ERROR: --paths entry is not a directory under {root} (paths-missing): {d}")
            if d:
                dirs.append(Path(d))
        explicit = True
    else:
        dirs, explicit = [], False
    files, scanned, skipped_binary, out = [], 0, 0, []
    scanned_dirs = set()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        if explicit:
            if not any(rel == d or d in rel.parents for d in dirs):
                continue
            scanned_dirs.update(d.as_posix() for d in dirs if d in rel.parents)
        else:
            hit_dir = next((part for part in rel.parts[:-1] if part in DEFAULT_DIRS), None)
            if hit_dir is None and not any(mk in rel.name for mk in FILE_MARKERS):
                continue
            if hit_dir:
                scanned_dirs.add(rel.parts[rel.parts.index(hit_dir)] if len(rel.parts) == 2 else "/".join(rel.parts[:rel.parts.index(hit_dir) + 1]))
        files.append(rel.as_posix())
        if p.stat().st_size > MAX_BYTES:
            skipped_binary += 1
            continue
        raw = p.read_bytes()
        if b"\x00" in raw[:8192]:
            skipped_binary += 1
            continue
        scanned += 1
        out.extend(scan_text(raw.decode("utf-8", errors="replace"), rel.as_posix(), allow))
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda x: (order[x["level"]], x["ruleId"], x["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], x["locations"][0]["physicalLocation"]["region"]["startLine"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "test-data-pii-scan", "version": "0.1.0"},
                                         "properties": {"directories": sorted(scanned_dirs), "files": len(files), "scanned": scanned,
                                                        "skipped": skipped_binary, "byRule": dict(sorted(Counter(r["ruleId"] for r in out).items()))}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
