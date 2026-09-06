#!/usr/bin/env python3
"""Check source files' leading comment blocks against a license header
template and emit a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    check_license_headers.py <repo> --header <header.txt>
                             [--ext py,js,ts,go,rs] [--exclude a,b]
                             [--git-years-json-file <file>]

Effect Ladder rung 1 (SDS-S-060): files are read; nothing is run.

The header template (see assets/header.example.txt for the shape) is
free text with two placeholders, `{year}` (matched by `\\d{4}(-\\d{4})?`)
and `{owner}` (matched by `.+?`). For each scanned file, the leading
comment block is the run of comment lines at the top of the file, after
an optional shebang line and, for `.py` files, an optional PEP 263
encoding declaration: consecutive `#` lines for `.py`; a single leading
`/* ... */` block, or consecutive `//` lines, for `.js`/`.ts`/`.go`/
`.rs`. The block's text (comment markers stripped) and the template are
each collapsed to single-spaced text and the template is matched as a
substring of the block (so trailing text such as an SPDX line does not
by itself break a match).

    license/header-missing   (warning) no leading comment block, or the
                              block contains neither "Copyright" nor
                              "Licensed under" - it is not a license
                              header at all.
    license/header-mismatch  (warning) the block contains "Copyright"
                              or "Licensed under" but does not match
                              the template.
    license/header-stale-year (info) only with --git-years-json-file
                              (a JSON object of path to integer year):
                              the header's last year is older than the
                              file's recorded year.
    license/spdx-missing     (info) the block has no
                              "SPDX-License-Identifier:" line; not
                              emitted when the header is missing.

Prints one finding-list; a tree with no findings yields an empty
`results` array (SDS-C-033). `tool.properties` carries `files`,
`withHeader`, `missing`, `mismatched`, `spdx`, and `gitYearsProvided`.

Exit 1 with "ERROR: ..." on stderr on failure: the repository path is
not a directory (repo-invalid); `--header` is missing or its file is
unreadable (header-unreadable); or `--git-years-json-file` is given
but is not a JSON object mapping paths to integer years
(years-unparseable).
"""
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".venv", "venv"}
DEFAULT_EXTS = ["py", "js", "ts", "go", "rs"]
LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2, "hint": 3}
ENCODING_RE = re.compile(r"^#.*coding[:=]\s*[-\w.]+")


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def collapse_ws(text):
    return re.sub(r"\s+", " ", text).strip()


def build_template_regex(template_text):
    collapsed = collapse_ws(template_text)
    parts = re.split(r"(\{year\}|\{owner\})", collapsed)
    pattern = []
    for part in parts:
        if part == "{year}":
            pattern.append(r"(?P<year>\d{4}(?:-\d{4})?)")
        elif part == "{owner}":
            pattern.append(r".+?")
        else:
            pattern.append(re.escape(part))
    return re.compile("".join(pattern))


def gather_files(root, exts, exclude):
    suffixes = {"." + e: e for e in exts}
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part in exclude for part in rel.parts):
            continue
        if p.suffix in suffixes:
            files.append((rel, suffixes[p.suffix]))
    return files


def leading_comment_block(text, lang):
    """Return (block_text, line_map) for the leading comment block, or
    (None, []) if the file has none. line_map is a list of (lineno,
    content) pairs, 1-based, content with the comment marker stripped."""
    lines = text.splitlines()
    idx = 0
    if idx < len(lines) and lines[idx].startswith("#!"):
        idx += 1
    if lang == "py" and idx < len(lines) and ENCODING_RE.match(lines[idx]):
        idx += 1

    line_map = []
    if lang == "py":
        while idx < len(lines) and lines[idx].lstrip().startswith("#"):
            content = lines[idx].lstrip()[1:]
            if content.startswith(" "):
                content = content[1:]
            line_map.append((idx + 1, content))
            idx += 1
    else:
        if idx < len(lines) and lines[idx].lstrip().startswith("/*"):
            while idx < len(lines):
                raw = lines[idx]
                stripped = raw.replace("/*", "").replace("*/", "").strip()
                if stripped.startswith("*"):
                    stripped = stripped[1:].strip()
                line_map.append((idx + 1, stripped))
                ended = "*/" in raw
                idx += 1
                if ended:
                    break
        elif idx < len(lines) and lines[idx].lstrip().startswith("//"):
            while idx < len(lines) and lines[idx].lstrip().startswith("//"):
                content = lines[idx].lstrip()[2:]
                if content.startswith(" "):
                    content = content[1:]
                line_map.append((idx + 1, content))
                idx += 1

    if not line_map:
        return None, []
    return "\n".join(c for _, c in line_map), line_map


def main():
    args = sys.argv[1:]

    def take(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"ERROR: {flag} requires a value")
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None

    header_path = take("--header")
    ext_arg = take("--ext")
    exclude_arg = take("--exclude")
    years_path = take("--git-years-json-file")

    if len(args) != 1:
        sys.exit("ERROR: usage: check_license_headers.py <repo> --header <header.txt> "
                  "[--ext py,js,ts,go,rs] [--exclude a,b] [--git-years-json-file <file>]")

    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")

    if not header_path:
        sys.exit("ERROR: --header <file> is required (header-unreadable)")
    try:
        header_text = Path(header_path).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"ERROR: cannot read --header file (header-unreadable): {header_path}: {e}")
    template_re = build_template_regex(header_text)

    exts = [e.strip() for e in ext_arg.split(",")] if ext_arg else list(DEFAULT_EXTS)
    exclude = {e.strip() for e in exclude_arg.split(",") if e.strip()} if exclude_arg else set()

    git_years = None
    if years_path:
        try:
            years_raw = json.loads(Path(years_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"ERROR: cannot read --git-years-json-file (years-unparseable): {years_path}: {e}")
        if not isinstance(years_raw, dict) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) for k, v in years_raw.items()
        ):
            sys.exit(f"ERROR: --git-years-json-file must be a JSON object of path to integer year "
                      f"(years-unparseable): {years_path}")
        git_years = years_raw

    files = gather_files(root, exts, exclude)

    results = []
    with_header = 0
    missing = 0
    mismatched = 0
    spdx_present = 0

    for rel, lang in files:
        uri = rel.as_posix()
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        block, line_map = leading_comment_block(text, lang)
        collapsed_block = collapse_ws(block) if block else ""
        is_license_like = bool(block) and ("Copyright" in collapsed_block or "Licensed under" in collapsed_block)
        match = template_re.search(collapsed_block) if block else None

        header_missing = False
        if match:
            with_header += 1
        elif is_license_like:
            mismatched += 1
            results.append(finding(
                "license/header-mismatch", "warning",
                f"{uri}'s leading comment block does not match the header template",
                uri, 1, {"file": uri},
            ))
        else:
            missing += 1
            header_missing = True
            results.append(finding(
                "license/header-missing", "warning",
                f"{uri} has no recognizable license header in its leading comment block",
                uri, 1, {"file": uri},
            ))

        if match and git_years is not None and uri in git_years:
            year_str = match.group("year")
            last_year = int(year_str.split("-")[-1])
            recorded = git_years[uri]
            if last_year < recorded:
                year_line = next((ln for ln, content in line_map if year_str in content), 1)
                results.append(finding(
                    "license/header-stale-year", "info",
                    f"{uri}'s header year {last_year} is older than the file's recorded year {recorded}",
                    uri, year_line, {"file": uri, "headerYear": last_year, "recordedYear": recorded},
                ))

        has_spdx = bool(block) and "SPDX-License-Identifier:" in collapsed_block
        if has_spdx:
            spdx_present += 1
        elif not header_missing:
            results.append(finding(
                "license/spdx-missing", "info",
                f"{uri}'s header has no SPDX-License-Identifier line",
                uri, 1, {"file": uri},
            ))

    results.sort(key=lambda r: (
        LEVEL_ORDER[r["level"]], r["ruleId"], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
    ))

    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{
            "tool": {
                "driver": {"name": "license-header-check", "version": "0.1.0"},
                "properties": {
                    "files": len(files),
                    "withHeader": with_header,
                    "missing": missing,
                    "mismatched": mismatched,
                    "spdx": spdx_present,
                    "gitYearsProvided": git_years is not None,
                },
            },
            "results": results,
        }],
    }, indent=2))


if __name__ == "__main__":
    main()
