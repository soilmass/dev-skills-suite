#!/usr/bin/env python3
"""Review a Dockerfile for the build-time and runtime choices that make
an image bigger, slower to rebuild, or less safe than it needs to be,
as a finding-list (kit/shapes/finding-list.schema.json).

Usage:
    review_dockerfile.py <repo|Dockerfile> [--allow-latest]

Effect Ladder rung 1: files are read; no image is built and no engine
is contacted.

A directory argument is scanned recursively (skipping .git,
node_modules, dist, build, vendor, target, __pycache__, .venv, venv)
for every file named `Dockerfile`, `Dockerfile.*`, or `*.dockerfile`.
A file argument is parsed directly, whatever its name. A path that
does not exist is `dockerfile-missing` when its name matches the
Dockerfile naming convention above (the caller clearly meant to point
at a Dockerfile that isn't there), or `repo-invalid` otherwise (it is
neither an existing directory, an existing file, nor a plausible
Dockerfile path).

Each Dockerfile is parsed instruction by instruction, honouring `\\`
line continuations and `#` comments; a non-empty logical line whose
first token is not a recognized Dockerfile instruction is
`dockerfile-unparseable`, naming the file and the line. A stage is one
`FROM ... [AS name]` and every instruction up to the next `FROM` or
the end of the file.

Rules emitted:

    docker/latest-tag          warning; a FROM image tagged :latest or
                               with no tag at all. --allow-latest
                               silences it. A FROM naming an earlier
                               stage (not a real base image) is exempt.
    docker/unpinned-base       info; a FROM with no @sha256: digest.
                               Skipped for a FROM where latest-tag
                               already fired, to avoid saying the same
                               thing twice.
    docker/root-user           warning; the final stage has no USER
                               instruction, or its last USER is root
                               or 0.
    docker/apt-no-cleanup      info; a RUN with apt-get install and no
                               rm -rf /var/lib/apt/lists in the same
                               RUN.
    docker/secret-in-arg-env   error; an ARG or ENV name matching
                               (?i)(secret|token|password|passwd|
                               api_key|apikey|private_key).
    docker/add-instead-of-copy info; an ADD whose source is not a URL
                               and not a .tar* archive.
    docker/no-healthcheck      info; the final stage has EXPOSE and no
                               HEALTHCHECK.
    docker/multi-stage-missing info; exactly one stage in the file,
                               with a RUN containing npm run build,
                               go build, cargo build, mvn package,
                               gradle build, or pip install.
    docker/copy-dot-before-deps warning; a COPY . / COPY . . / ADD .
                               instruction earlier in a stage than the
                               first dependency-install RUN in that
                               same stage (npm ci, npm install, pip
                               install, poetry install, go mod
                               download, cargo fetch, bundle install)
                               — the whole build context is copied
                               before the layer that would let Docker
                               cache the dependency install survives
                               an unrelated source edit.

Every location is the Dockerfile's path with region.startLine set to
the instruction's first line (the FROM line of the final stage when a
finding is about an instruction that is absent, such as a missing
USER). `tool.properties` carries `files`, `stages`, `instructions`,
and `byRule` (a count per ruleId).

Prints one finding-list; a directory with no Dockerfiles yields an
empty `results` array and `tool.properties.files` 0 (SDS-C-033) —
not a failure. Exit 1 with "ERROR: ..." on stderr for `repo-invalid`,
`dockerfile-missing`, or `dockerfile-unparseable` as described above.
"""
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target", "__pycache__", ".venv", "venv"}

INSTRUCTIONS = {
    "FROM", "RUN", "CMD", "LABEL", "EXPOSE", "ENV", "ADD", "COPY",
    "ENTRYPOINT", "VOLUME", "USER", "WORKDIR", "ARG", "ONBUILD",
    "STOPSIGNAL", "HEALTHCHECK", "SHELL", "MAINTAINER",
}

SECRET_RE = re.compile(r"(?i)(secret|token|password|passwd|api_key|apikey|private_key)")
DIGEST_RE = re.compile(r"@sha256:[0-9a-fA-F]{64}")
DEPS_RE = re.compile(r"\b(npm ci|npm install|pip install|poetry install|go mod download|cargo fetch|bundle install)\b")
BUILD_RE = re.compile(r"\b(npm run build|go build|cargo build|mvn package|gradle build|pip install)\b")
TAR_RE = re.compile(r"\.tar(\.\w+)?$", re.I)
LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2, "hint": 3}


def is_dockerfile_name(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".dockerfile")


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line is not None:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def gather_dockerfiles(root: Path):
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if is_dockerfile_name(p.name):
            out.append(p)
    return out


def parse_instructions(path: Path):
    """Return [(keyword, args, line)] for every logical instruction in
    the file, honouring `\\` continuations and `#` comments. Exits with
    dockerfile-unparseable on the first line whose first token is not a
    recognized Dockerfile instruction."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        start_line = i + 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        logical = raw.rstrip("\n")
        while logical.rstrip().endswith("\\") and i + 1 < n:
            i += 1
            logical = logical.rstrip()[:-1].rstrip() + " " + lines[i].strip()
        i += 1
        logical = logical.strip()
        if not logical:
            continue
        parts = logical.split(None, 1)
        keyword = parts[0].upper()
        if keyword not in INSTRUCTIONS:
            sys.exit(
                f"ERROR: {path} line {start_line}: {parts[0]!r} is not a recognized "
                f"Dockerfile instruction (dockerfile-unparseable)"
            )
        args = parts[1] if len(parts) > 1 else ""
        out.append((keyword, args, start_line))
    return out


def split_stages(instructions):
    """Group instructions into stages, one per FROM. Instructions before
    the first FROM (a global ARG) are dropped from stage grouping but
    remain in the flat instruction list callers also have access to."""
    stages = []
    cur = None
    for kw, args, line in instructions:
        if kw == "FROM":
            cur = {"from_args": args, "from_line": line, "instructions": []}
            stages.append(cur)
        elif cur is not None:
            cur["instructions"].append((kw, args, line))
    return stages


def parse_from(args: str):
    tokens = [t for t in args.split() if not t.startswith("--")]
    if not tokens:
        return None, None
    image = tokens[0]
    name = tokens[2] if len(tokens) >= 3 and tokens[1].upper() == "AS" else None
    return image, name


def image_ref_parts(image: str):
    if "@" in image:
        base, digest = image.split("@", 1)
        has_digest = bool(DIGEST_RE.search("@" + digest))
    else:
        base, has_digest = image, False
    last = base.rsplit("/", 1)[-1]
    if ":" in last:
        tag = last.rsplit(":", 1)[1]
    else:
        tag = None
    return tag, has_digest


def arg_env_names(kw: str, args: str):
    args = args.strip()
    if not args:
        return []
    if kw == "ARG":
        return [tok.split("=", 1)[0] for tok in args.split()]
    tokens = args.split()
    if any("=" in t for t in tokens):
        return [t.split("=", 1)[0] for t in tokens if "=" in t]
    return [tokens[0]] if tokens else []


def is_dot_copy(kw: str, args: str) -> bool:
    if kw not in ("COPY", "ADD"):
        return False
    tokens = [t for t in args.split() if not t.startswith("--")]
    return bool(tokens) and tokens[0] == "."


def review_file(uri: str, instructions, stages, allow_latest: bool):
    out = []

    def emit(rule, level, text, line, props):
        out.append(finding(rule, level, text, uri, line, props))

    # Stage names seen so far, for the "FROM references an earlier stage" exemption.
    seen_stage_names = set()
    for idx, st in enumerate(stages):
        image, name = parse_from(st["from_args"])
        st["is_stage_ref"] = image is not None and image.lower() in seen_stage_names
        if name:
            seen_stage_names.add(name.lower())

        if image is None or st["is_stage_ref"]:
            continue

        tag, has_digest = image_ref_parts(image)
        is_latest = tag is None or tag == "latest"
        latest_fired = False
        if is_latest and not allow_latest:
            emit(
                "docker/latest-tag", "warning",
                f"FROM {image} has no tag or uses :latest; pin an explicit version tag",
                st["from_line"], {"stage": idx, "image": image},
            )
            latest_fired = True
        if not has_digest and not latest_fired:
            emit(
                "docker/unpinned-base", "info",
                f"FROM {image} has no @sha256 digest; pin a digest for a reproducible build",
                st["from_line"], {"stage": idx, "image": image},
            )

    # Rules scoped to individual instructions, wherever they occur.
    for kw, args, line in instructions:
        if kw == "RUN":
            low = args.lower()
            if "apt-get install" in low and "rm -rf /var/lib/apt/lists" not in low:
                emit(
                    "docker/apt-no-cleanup", "info",
                    "RUN installs apt packages but does not clean /var/lib/apt/lists in the same layer",
                    line, {},
                )
        elif kw in ("ARG", "ENV"):
            for nm in arg_env_names(kw, args):
                if SECRET_RE.search(nm):
                    emit(
                        "docker/secret-in-arg-env", "error",
                        f"{kw} {nm} looks like a secret; pass it as a build secret or inject it at runtime instead",
                        line, {"instruction": kw, "name": nm},
                    )
        elif kw == "ADD":
            tokens = [t for t in args.split() if not t.startswith("--")]
            if tokens:
                src = tokens[0]
                if not src.startswith(("http://", "https://")) and not TAR_RE.search(src):
                    emit(
                        "docker/add-instead-of-copy", "info",
                        f"ADD {src} is a plain file or directory; COPY does the same thing without ADD's URL/archive behavior",
                        line, {"source": src},
                    )

    # Rules scoped to a single stage.
    for idx, st in enumerate(stages):
        dot_line = None
        deps_line = None
        for kw, args, line in st["instructions"]:
            if dot_line is None and is_dot_copy(kw, args):
                dot_line = line
            if deps_line is None and kw == "RUN" and DEPS_RE.search(args):
                deps_line = line
        if dot_line is not None and deps_line is not None and dot_line < deps_line:
            emit(
                "docker/copy-dot-before-deps", "warning",
                "COPY . / ADD . copies the whole build context before dependencies are installed; "
                "installing dependencies first keeps that layer cached across unrelated source edits",
                dot_line, {"stage": idx},
            )

    if len(stages) == 1:
        for kw, args, line in stages[0]["instructions"]:
            if kw == "RUN" and BUILD_RE.search(args):
                emit(
                    "docker/multi-stage-missing", "info",
                    "single-stage build runs a build command; a multi-stage build can drop the build "
                    "toolchain from the final image",
                    line, {"stage": 0},
                )
                break

    if stages:
        final_idx = len(stages) - 1
        final = stages[final_idx]
        users = [(args, line) for kw, args, line in final["instructions"] if kw == "USER"]
        if not users:
            emit(
                "docker/root-user", "warning",
                "final stage has no USER instruction; the image runs as root",
                final["from_line"], {"stage": final_idx},
            )
        else:
            last_args, last_line = users[-1]
            user_name = last_args.split()[0] if last_args.split() else ""
            if user_name in ("root", "0"):
                emit(
                    "docker/root-user", "warning",
                    f"final stage's last USER is {user_name}; the image runs as root",
                    last_line, {"stage": final_idx},
                )

        has_expose = any(kw == "EXPOSE" for kw, _, _ in final["instructions"])
        has_health = any(kw == "HEALTHCHECK" for kw, _, _ in final["instructions"])
        if has_expose and not has_health:
            expose_line = next(line for kw, _, line in final["instructions"] if kw == "EXPOSE")
            emit(
                "docker/no-healthcheck", "info",
                "final stage exposes a port but declares no HEALTHCHECK",
                expose_line, {"stage": final_idx},
            )

    return out


def main():
    args = sys.argv[1:]
    allow_latest = "--allow-latest" in args
    args = [a for a in args if a != "--allow-latest"]
    if len(args) != 1:
        sys.exit("ERROR: usage: review_dockerfile.py <repo|Dockerfile> [--allow-latest]")

    target = Path(args[0])

    if target.is_dir():
        files = gather_dockerfiles(target)
        entries = [(f, f.relative_to(target).as_posix()) for f in files]
    elif target.is_file():
        entries = [(target, target.name)]
    elif is_dockerfile_name(target.name):
        sys.exit(f"ERROR: {target} does not exist (dockerfile-missing)")
    else:
        sys.exit(f"ERROR: {target} is neither a directory nor a file (repo-invalid)")

    all_findings = []
    by_rule = {}
    total_stages = 0
    total_instructions = 0

    for path, uri in entries:
        instructions = parse_instructions(path)
        stages = split_stages(instructions)
        total_instructions += len(instructions)
        total_stages += len(stages)
        for f in review_file(uri, instructions, stages, allow_latest):
            all_findings.append(f)
            by_rule[f["ruleId"]] = by_rule.get(f["ruleId"], 0) + 1

    all_findings.sort(key=lambda r: (
        LEVEL_ORDER[r["level"]],
        r["ruleId"],
        r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
        r["locations"][0]["physicalLocation"].get("region", {}).get("startLine", 0),
    ))

    print(json.dumps({
        "version": "sds-finding-list-1.0",
        "runs": [{
            "tool": {
                "driver": {"name": "dockerfile-review", "version": "0.1.0"},
                "properties": {
                    "files": len(entries),
                    "stages": total_stages,
                    "instructions": total_instructions,
                    "byRule": dict(sorted(by_rule.items())),
                },
            },
            "results": all_findings,
        }],
    }, indent=2))


if __name__ == "__main__":
    main()
