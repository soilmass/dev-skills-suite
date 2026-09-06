# Dockerfile Rules: Rationale and Fix

Loaded on demand from SKILL.md's Analyze stage — only when a finding's
fix is not obvious. Each section below names the rule the script
emits, why it matters, and the fix. All nine rules follow Docker's own
"Dockerfile best practices" guide (docs.docker.com), cited by name in
each section rather than fetched live.

## docker/latest-tag

**Rationale.** `:latest`, or no tag at all, resolves to whatever the
registry currently serves — a build run today can pull a different
image than the same build run tomorrow, and a rollback cannot pin the
image it wants. Docker's Dockerfile best practices guide recommends
avoiding `latest` for exactly this reason.

**Fix.** Pin an explicit version tag, e.g. `FROM node:20-slim` instead
of `FROM node:latest` or `FROM node`.

## docker/unpinned-base

**Rationale.** A tag can be retagged to point at a different image at
any time; only a digest (`@sha256:...`) is immutable. Two builds of
the same Dockerfile a month apart can otherwise pull different bytes
under the same tag.

**Fix.** Add the digest alongside the tag:
`FROM node:20-slim@sha256:<digest>`. `docker pull` and `docker inspect`
print the digest for a given tag.

## docker/root-user

**Rationale.** A container with no `USER` instruction (or one that
switches back to `root`) runs its process as root inside the
container, which is also root's UID in the default namespace. A
container escape or an arbitrary-file-write vulnerability in the
application is worse when the process already has full privileges
inside the image.

**Fix.** Create a non-root user and switch to it before the final
`CMD`/`ENTRYPOINT`: `RUN useradd -m app` then `USER app`.

## docker/apt-no-cleanup

**Rationale.** `apt-get install` populates `/var/lib/apt/lists` with
package indexes. Because a Docker layer is immutable once written, a
later `RUN rm -rf /var/lib/apt/lists/*` in a *different* instruction
does not shrink the image — the index files still live in the earlier
layer.

**Fix.** Clean up in the same `RUN` as the install:
`RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*`.

## docker/secret-in-arg-env

**Rationale.** An `ARG` is visible to anyone who can run
`docker history` against the built image, and both `ARG` and `ENV`
values are visible to every later instruction and, for `ENV`, baked
into the final image's metadata. Neither is a safe place for a
secret, even one that is not written into the filesystem.

**Fix.** Use a build-time secret mount (`RUN --mount=type=secret`) for
build-time credentials, or inject the value at container start from
the orchestrator's own secret store — never bake it into the image.

## docker/add-instead-of-copy

**Rationale.** `ADD` silently does two things `COPY` does not: it
fetches a URL, and it auto-extracts a recognized archive. For a plain
local file or directory, that hidden behavior is a surprise waiting to
happen (a future rename to a `.tar.gz` path would suddenly extract
instead of copy). Docker's Dockerfile best practices guide recommends
`COPY` for anything that is not one of `ADD`'s two special cases.

**Fix.** Replace `ADD ./src /app/src` with
`COPY ./src /app/src`; keep `ADD` only for a URL source or a `.tar*`
archive that should be extracted on the way in.

## docker/no-healthcheck

**Rationale.** Without a `HEALTHCHECK`, `docker ps` and an
orchestrator's readiness probe can only see whether the process is
still running, not whether it is actually serving the port it
`EXPOSE`s — a hung server behind a dead event loop looks identical to
a healthy one.

**Fix.** Add a `HEALTHCHECK` that hits the exposed port, e.g.
`HEALTHCHECK CMD curl -f http://localhost:3000/ || exit 1`.

## docker/multi-stage-missing

**Rationale.** A single-stage build that runs a compiler, bundler, or
package manager's build step ships that entire toolchain — and every
package it pulled in to run it — in the final image, growing both the
attack surface and the pull size for something the running container
never uses again after the build finished.

**Fix.** Split the build into a `build` stage that runs the build
command and a final stage, based on a smaller runtime image, that
only `COPY --from=build`s the produced artifact.

## docker/copy-dot-before-deps

**Rationale.** Docker caches a layer until an earlier layer changes.
`COPY . .` before the dependency-install command means every layer
from that `COPY` onward — including the install itself — is
invalidated by any change to any file, so a one-line source edit
forces a full dependency reinstall on the next build.

**Fix.** Copy only the dependency manifest first, install, then copy
the rest of the build context:

```
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
```
