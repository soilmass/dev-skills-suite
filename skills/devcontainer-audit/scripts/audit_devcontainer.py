#!/usr/bin/env python3
"""Audit a repository's dev container definition — .devcontainer/
devcontainer.json (JSONC) and the Dockerfile it builds — for the
choices that make it slow, non-reproducible, or unsafe, as a
finding-list (kit/shapes/finding-list.schema.json).

Usage:
    audit_devcontainer.py <repo-path>

Effect Ladder rung 1 (SDS-S-060): files are read; no image is built
or pulled. The definition is located per the Dev Container spec
(containers.dev): .devcontainer/devcontainer.json, .devcontainer.json,
or .devcontainer/<name>/devcontainer.json. The Dockerfile is the one
`build.dockerfile` names (relative to the definition) or, when the
definition uses `image`, none.

Rules emitted:

    container/unpinned-image      FROM <image> with no tag or :latest,
                                  or `image` / a feature reference
                                  without a tag or with :latest ->
                                  warning (the environment changes
                                  under you)
    container/root-user           no USER instruction in the Dockerfile
                                  and no remoteUser/containerUser in
                                  the definition -> warning (everything
                                  runs as root; files created in the
                                  workspace are root-owned)
    container/apt-no-cleanup      apt-get install without
                                  `rm -rf /var/lib/apt/lists/*` in the
                                  same RUN -> info (image bloat)
    container/copy-before-install COPY . (or ADD .) before the RUN that
                                  installs dependencies -> warning
                                  (every source edit busts the
                                  dependency layer cache)
    container/secret-in-build     ARG or ENV whose name looks like a
                                  secret -> warning (build args and
                                  env are baked into image metadata)
    container/no-post-create      no postCreateCommand or
                                  postAttachCommand/updateContentCommand
                                  -> info (dependencies must be
                                  installed by hand after open)
    container/no-definition       no dev container definition found ->
                                  info (nothing to audit; say so)

Judging which finding matters for this team — a root user in a
throwaway CI container, an unpinned internal base image that is
itself pinned upstream — is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; a well-formed definition yields an empty
`results` array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for
a path that is not a directory (repo-invalid) or a definition that is
not valid JSONC (definition-unparseable).
"""
import json
import re
import sys
from pathlib import Path

SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE|CREDENTIAL)", re.I)
# manifest-driven dependency installs (the layer a COPY . busts); OS packages via apt are not this
INSTALL_RE = re.compile(r"\b(pip3?\s+install|npm\s+(ci|install)|yarn\s+install|pnpm\s+install|poetry\s+install|uv\s+sync|bundle\s+install|cargo\s+build|go\s+mod\s+download)\b")


def finding(rule, level, text, uri, line, props):
    loc = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if line:
        loc["physicalLocation"]["region"] = {"startLine": line}
    return {"ruleId": rule, "level": level, "message": {"text": text}, "locations": [loc], "properties": props}


def strip_jsonc(text):
    out, i, n = [], 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True; out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))  # trailing commas


def find_definition(root):
    for cand in (root / ".devcontainer" / "devcontainer.json", root / ".devcontainer.json"):
        if cand.is_file():
            return cand
    sub = sorted((root / ".devcontainer").glob("*/devcontainer.json")) if (root / ".devcontainer").is_dir() else []
    return sub[0] if sub else None


def unpinned(ref):
    ref = ref.split("@")[0]
    name = ref.rsplit("/", 1)[-1]
    return ":" not in name or name.endswith(":latest")


def audit_dockerfile(path, uri, out):
    lines = path.read_text(encoding="utf-8").splitlines()
    # join continuation lines, remembering the first line number of each instruction
    instr, buf, start = [], [], None
    for i, raw in enumerate(lines, start=1):
        s = raw.rstrip()
        if not buf and (not s.strip() or s.lstrip().startswith("#")):
            continue
        if start is None:
            start = i
        buf.append(s.rstrip("\\").strip())
        if not s.endswith("\\"):
            instr.append((start, " ".join(buf)))
            buf, start = [], None
    has_user, copied_all_at, install_seen = False, None, False
    for ln, text in instr:
        kw, _, rest = text.partition(" ")
        kw = kw.upper()
        if kw == "FROM":
            image = rest.split()[0]
            if image.lower() != "scratch" and unpinned(image) and "$" not in image:
                out.append(finding("container/unpinned-image", "warning", f"FROM {image}: no tag or :latest; pin a tag (better, a digest) so the environment is reproducible", uri, ln, {"image": image}))
        elif kw == "USER":
            has_user = rest.strip() not in ("root", "0")
        elif kw in ("COPY", "ADD"):
            srcs = [t for t in rest.split() if not t.startswith("--")][:-1]
            if any(s in (".", "./", "/") for s in srcs) and not install_seen:
                copied_all_at = copied_all_at or ln
        elif kw == "RUN":
            if INSTALL_RE.search(rest):
                install_seen = True
                if copied_all_at is not None:
                    out.append(finding("container/copy-before-install", "warning", f"the whole tree was copied at line {copied_all_at} before this dependency install; every source edit rebuilds the dependency layer — copy the manifest first, install, then copy the rest", uri, ln, {"copyLine": copied_all_at}))
                    copied_all_at = None
            if "apt-get install" in rest and "/var/lib/apt/lists" not in rest:
                out.append(finding("container/apt-no-cleanup", "info", "apt-get install without rm -rf /var/lib/apt/lists/* in the same RUN; the package index stays in the layer", uri, ln, {}))
        elif kw in ("ARG", "ENV"):
            name = rest.split("=")[0].split()[0] if rest.strip() else ""
            if SECRET_RE.search(name):
                out.append(finding("container/secret-in-build", "warning", f"{kw} {name}: build arguments and environment are baked into image metadata; pass secrets with --mount=type=secret or at run time", uri, ln, {"name": name, "instruction": kw}))
    return has_user


def main():
    args = sys.argv[1:]
    if len(args) != 1:
        sys.exit("ERROR: usage: audit_devcontainer.py <repo-path>")
    root = Path(args[0])
    if not root.is_dir():
        sys.exit(f"ERROR: not a directory (repo-invalid): {root}")
    out = []
    defn = find_definition(root)
    if defn is None:
        out.append(finding("container/no-definition", "info", "no dev container definition (.devcontainer/devcontainer.json) found; nothing to audit", ".devcontainer/devcontainer.json", None, {}))
    else:
        uri = defn.relative_to(root).as_posix()
        try:
            cfg = json.loads(strip_jsonc(defn.read_text(encoding="utf-8")))
            assert isinstance(cfg, dict)
        except (json.JSONDecodeError, UnicodeDecodeError, AssertionError) as e:
            sys.exit(f"ERROR: {uri} is not valid JSONC (definition-unparseable): {e}")
        has_user = bool(cfg.get("remoteUser") or cfg.get("containerUser"))
        image = cfg.get("image")
        if isinstance(image, str) and unpinned(image):
            out.append(finding("container/unpinned-image", "warning", f"image {image}: no tag or :latest; pin a tag or digest", uri, None, {"image": image}))
        for ref in (cfg.get("features") or {}):
            if unpinned(ref):
                out.append(finding("container/unpinned-image", "warning", f"feature {ref}: no version tag or :latest; pin the feature version", uri, None, {"feature": ref}))
        build = cfg.get("build") or {}
        dockerfile = build.get("dockerfile") or cfg.get("dockerFile")
        if dockerfile:
            df = defn.parent / build.get("context", ".") / dockerfile if not Path(dockerfile).is_absolute() else Path(dockerfile)
            df = (defn.parent / dockerfile) if not df.is_file() else df
            if df.is_file():
                has_user = audit_dockerfile(df, df.relative_to(root).as_posix(), out) or has_user
            else:
                out.append(finding("container/no-definition", "info", f"build.dockerfile {dockerfile} not found beside the definition", uri, None, {"dockerfile": dockerfile}))
        if not has_user:
            out.append(finding("container/root-user", "warning", "no USER in the Dockerfile and no remoteUser/containerUser in the definition; everything runs as root and workspace files come out root-owned", uri, None, {}))
        if not any(cfg.get(k) for k in ("postCreateCommand", "postAttachCommand", "updateContentCommand", "onCreateCommand")):
            out.append(finding("container/no-post-create", "info", "no postCreateCommand (or onCreate/updateContent/postAttach); dependencies must be installed by hand after the container opens", uri, None, {}))
    order = {"warning": 0, "info": 1}
    out.sort(key=lambda r: (order[r["level"]], r["ruleId"], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], r["locations"][0]["physicalLocation"].get("region", {}).get("startLine", 0)))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "devcontainer-audit", "version": "0.1.0"},
                                         "properties": {"definition": defn.relative_to(root).as_posix() if defn else None}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
