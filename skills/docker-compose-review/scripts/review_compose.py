#!/usr/bin/env python3
"""Review a Docker Compose file for the service definitions that bite in
production or leak in development, as a finding-list
(kit/shapes/finding-list.schema.json).

Usage:
    review_compose.py <compose.yml> [--profile dev|prod]

Effect Ladder rung 1 (SDS-S-060): the file is read; no engine is
contacted. Requires PyYAML. The file follows the Compose
Specification (compose-spec.io): a `services` mapping, each service
with image/build, environment, ports, volumes, depends_on,
healthcheck, deploy.resources, restart, privileged, network_mode.

Rules emitted (per service):

    compose/unpinned-image        image with no tag or :latest -> warning
    compose/no-healthcheck        no healthcheck (and no build-time one
                                  the file can see) -> info; depends_on
                                  conditions and orchestrators need it
    compose/depends-on-no-condition depends_on in list form, or a map
                                  entry without condition -> info (the
                                  dependency starts, not becomes ready)
    compose/privileged            privileged: true, or cap_add SYS_ADMIN
                                  -> warning
    compose/host-network          network_mode: host, or pid: host ->
                                  warning
    compose/secret-literal        an environment key that looks like a
                                  secret (KEY, TOKEN, SECRET, PASSWORD,
                                  PRIVATE, CREDENTIAL) with a literal
                                  value (not ${VAR} interpolation, not
                                  a Compose `secrets` reference) ->
                                  warning
    compose/root-bind-mount       a bind mount of / or the Docker socket
                                  -> warning
    compose/port-all-interfaces   a published port with no host IP
                                  (0.0.0.0) -> info with --profile dev
                                  (the default), warning with prod
    compose/no-resource-limits    no deploy.resources.limits (memory or
                                  cpus) -> info; one runaway service
                                  starves the host
    compose/no-restart-policy     no restart / deploy.restart_policy ->
                                  info with prod, silent with dev

`tool.properties` carries the service names and the profile. Which
finding matters for this file — a dev-only compose where host ports
are the point — is the skill's Analyze stage (SDS-S-061).

Prints one finding-list; a well-formed file yields an empty `results`
array (SDS-C-033). Exit 1 with "ERROR: ..." on stderr for a file that
cannot be read or parsed (compose-unparseable), one with no
`services` mapping (compose-invalid), or an unknown --profile
(profile-invalid).
"""
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("ERROR: PyYAML is required (pip install pyyaml)")

SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE|CREDENTIAL)", re.I)


def finding(rule, level, text, uri, props):
    return {"ruleId": rule, "level": level, "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}}}], "properties": props}


def env_items(env):
    if isinstance(env, dict):
        return [(k, "" if v is None else str(v)) for k, v in env.items()]
    if isinstance(env, list):
        out = []
        for item in env:
            k, _, v = str(item).partition("=")
            out.append((k, v))
        return out
    return []


def unpinned(image):
    name = str(image).split("@")[0].rsplit("/", 1)[-1]
    return ":" not in name or name.endswith(":latest")


def main():
    args = sys.argv[1:]
    profile = "dev"
    if "--profile" in args:
        i = args.index("--profile")
        if i + 1 >= len(args):
            sys.exit("ERROR: --profile requires a value")
        profile = args[i + 1]
        del args[i:i + 2]
    if profile not in ("dev", "prod"):
        sys.exit(f"ERROR: --profile must be dev or prod, not {profile!r} (profile-invalid)")
    if len(args) != 1:
        sys.exit("ERROR: usage: review_compose.py <compose.yml> [--profile dev|prod]")
    path = Path(args[0])
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        sys.exit(f"ERROR: could not read {path} (compose-unparseable): {e}")
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        sys.exit(f"ERROR: {path} has no services mapping (compose-invalid)")
    uri = path.name
    out = []
    for name, svc in doc["services"].items():
        if not isinstance(svc, dict):
            continue
        p = {"service": name}
        image = svc.get("image")
        if image and unpinned(image):
            out.append(finding("compose/unpinned-image", "warning", f"{name}: image {image} has no tag or :latest; pin a tag or digest", uri, {**p, "image": str(image)}))
        if "healthcheck" not in svc:
            out.append(finding("compose/no-healthcheck", "info", f"{name}: no healthcheck; dependents cannot wait for readiness", uri, p))
        dep = svc.get("depends_on")
        if isinstance(dep, list) and dep:
            out.append(finding("compose/depends-on-no-condition", "info", f"{name}: depends_on {dep} is a list; the dependency is started, not ready — use condition: service_healthy", uri, {**p, "dependsOn": dep}))
        elif isinstance(dep, dict):
            missing = [d for d, cfg in dep.items() if not (isinstance(cfg, dict) and cfg.get("condition"))]
            if missing:
                out.append(finding("compose/depends-on-no-condition", "info", f"{name}: depends_on {missing} has no condition", uri, {**p, "dependsOn": missing}))
        if svc.get("privileged") is True or any(str(c).upper() in ("SYS_ADMIN", "ALL") for c in svc.get("cap_add") or []):
            out.append(finding("compose/privileged", "warning", f"{name}: privileged or SYS_ADMIN; the container can escape to the host", uri, p))
        if svc.get("network_mode") == "host" or svc.get("pid") == "host":
            out.append(finding("compose/host-network", "warning", f"{name}: host network or pid namespace; isolation is off", uri, p))
        for k, v in env_items(svc.get("environment")):
            if SECRET_RE.search(k) and v and not v.startswith("$") and not v.startswith("/run/secrets"):
                out.append(finding("compose/secret-literal", "warning", f"{name}: environment {k} carries a literal value; use ${{{k}}} from the environment or a Compose secret", uri, {**p, "key": k}))
        for vol in svc.get("volumes") or []:
            src = vol.get("source", "") if isinstance(vol, dict) else str(vol).split(":")[0]
            if src in ("/", "/var/run/docker.sock"):
                out.append(finding("compose/root-bind-mount", "warning", f"{name}: bind mounts {src}; the container owns the host", uri, {**p, "source": src}))
        for port in svc.get("ports") or []:
            spec = str(port.get("published", "")) if isinstance(port, dict) else str(port)
            host_ip = port.get("host_ip") if isinstance(port, dict) else (spec.split(":")[0] if spec.count(":") == 2 else None)
            if not host_ip:
                out.append(finding("compose/port-all-interfaces", "warning" if profile == "prod" else "info", f"{name}: port {spec} is published on all interfaces; bind 127.0.0.1 unless it must be reachable", uri, {**p, "port": spec}))
        limits = ((svc.get("deploy") or {}).get("resources") or {}).get("limits") or {}
        if not limits.get("memory") and not limits.get("cpus") and not svc.get("mem_limit"):
            out.append(finding("compose/no-resource-limits", "info", f"{name}: no memory or cpu limit; one runaway service starves the host", uri, p))
        if profile == "prod" and not svc.get("restart") and not (svc.get("deploy") or {}).get("restart_policy"):
            out.append(finding("compose/no-restart-policy", "info", f"{name}: no restart policy; a crash stays down", uri, p))
    order = {"warning": 0, "info": 1}
    out.sort(key=lambda r: (order[r["level"]], r["properties"]["service"], r["ruleId"]))
    print(json.dumps({"version": "sds-finding-list-1.0",
                      "runs": [{"tool": {"driver": {"name": "docker-compose-review", "version": "0.1.0"},
                                         "properties": {"profile": profile, "services": sorted(doc["services"])}},
                                "results": out}]}, indent=2))


if __name__ == "__main__":
    main()
