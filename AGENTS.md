# AGENTS.md — instructions for LLM agents working in a cupli workspace

This document is for AI agents (Claude Code, Cursor, GitHub Copilot,
Codex, Aider) that need to **read and edit `space.cupli.yaml`** in a
project that uses cupli. Read this once, then operate confidently.

> If you're an agent modifying **cupli's own source code**, that's a
> different document. See [`README.md`](README.md) Contributing section.

---

## What cupli is

A CLI that turns one `space.cupli.yaml` into one running
docker-compose project. It manages:

1. **Multi-repo workspaces** — each app/mount may have `repo:` + `branch:`.
   Cupli clones them under `src/apps/<name>` etc.
2. **Service binding** — every app binds to one or more compose-services.
   Forms: implicit, string, inline dict, multi-service map (see below).
3. **Variable scope** — space → bases (C3) → app, with `${VAR}` and
   `${VAR:-default}` interpolation.
4. **Lifecycle** — `cupli up/down/restart/logs/ps/build/pull`,
   `cupli exec/run/shell`, `cupli git status/pull/fetch/checkout`,
   `cupli mounts attach/detach`, `cupli sc <name>`.
5. **Validation** — every YAML is validated against a Pydantic schema.
   Failures surface with `file:line:col` per field.

The authoritative schema is in [`space.schema.json`](space.schema.json).
Every example YAML carries a `# yaml-language-server: $schema=...`
directive on line 1.

---

## The mental model in 30 seconds

```
space.cupli.yaml
├─ name:              project + network name
├─ vars:              shared across the whole stack
├─ bases:             reusable templates (vars + composes + ...)
├─ apps:              what cupli starts/stops
│   └─ each app binds to compose-services via:
│      • implicit:      service name = app name
│      • service: name  →  rename binding to existing compose service
│      • service: {...} →  inline single-service (any compose attrs)
│      • services: {...}→  multi-service map (compound app)
│      • services: [a,b]→  same, list-form shorthand for empty overrides
├─ mounts:            toggleable bind-mounts (cupli mounts attach/detach);
│                     `host_bridge:` keeps an inverse host symlink for IDEs
├─ exports:           materialise container-built dirs (node_modules) to host
├─ networks:          docker-compose `networks:` block (compose-spec verbatim)
├─ volumes:           top-level `volumes:` block (named volumes, verbatim)
├─ secrets:           top-level `secrets:` block (secret definitions, verbatim)
├─ configs:           top-level `configs:` block (config definitions, verbatim)
└─ commands:          shortcuts (cupli sc <name> / cupli <name>); support
                      groups, typed args, multi-line run, multi-container
```

Cupli writes three generated files under `.locals/<space>/state/` on
every invocation:

* `docker-compose.pre.yml` — defaults (network, `container_name`) plus any
  top-level `volumes:` / `secrets:` / `configs:` blocks (verbatim).
* `docker-compose.inline.yml` — services declared inline.
* `docker-compose.post.yml` — `environment` / `ports` / `volumes` (mounts +
  `bind-seeded` export binds) / `depends_on` / `networks` injection.

Plus `override.env` with all space-scope vars + per-component
`<NAME>_APP_PATH` etc. that docker-compose substitutes into compose
files.

---

## Quick rules — what you must / must not do

### MUST

* **Keep schema_version: 1.** Don't change it.
* **Match `name:` to `^[A-Za-z][A-Za-z0-9_-]*$`.**
* **Make `service:` and `services:` mutually exclusive.** Pydantic
  raises `E002` otherwise.
* **Inside `service: {...}` or `services.<n>: {...}`, write any
  docker-compose service attribute verbatim** (`image`, `build`,
  `command`, `environment`, `depends_on`, `healthcheck`, `volumes`,
  `restart`, `ulimits`, `cap_add`, etc.). Cupli only intercepts
  `vars` and `ports`.
* **Use `${VAR}`, `${VAR:-default}`, or bare `$VAR` for interpolation.**
  Prefer the braced form next to other text. `$$` is an escape for a literal
  `$` (docker-compose convention), so a value containing a real `$` must
  double it (e.g. a password `p$$w0rd`).
* **`envs:` file VALUES are interpolated by cupli too.** A value inside an env
  file may reference the cupli scope — top-level `vars`, top-level `envs`, and
  earlier env layers in the same component — e.g. `back.env` containing
  `DATABASE_URL=postgres://db:${POSTGRES_PORT}/app` resolves `${POSTGRES_PORT}`
  from `vars`. So port-dependent wiring and credential reuse CAN live in env
  files, not only in `vars:`. (Resolution order: process-env → space auto-vars
  → space `envs` → space `vars` → base `envs`/`vars` → app `envs`/`vars`.)
* **Use auto-vars when referring to paths:**
    * `${SPACE_PATH}`, `${APPS_PATH}`, `${BASES_PATH}`, `${MOUNTS_PATH}`,
      `${LOCALS_PATH}` — space scope.
    * `${APP_PATH}`, `${APP_NAME}`, `${APP_LOCAL_PATH}` — self-reference
      inside the current app / base / mount (cupli stores every
      component's path as `APP_PATH` regardless of kind — the name is a
      leftover from the apps-only era).
    * `${MOUNT_PATH}`, `${MOUNT_EXEC_PATH}` — inside a mount.
    * `${<NAME>_APP_PATH}`, `${<NAME>_BASE_PATH}`, `${<NAME>_MOUNT_PATH}`
      — cross-component (`<NAME>` is the component name upper-cased with
      `-` → `_`).
* **Inline compose-spec is substituted by docker-compose, not cupli.**
  Inside `service: {build: {context: ${API_APP_PATH}}}` use the
  per-component path-var (`${API_APP_PATH}`), NOT bare `${APP_PATH}`.
  Cupli writes `<NAME>_APP_PATH` into `override.env` so compose can
  resolve them; bare `APP_PATH` is only set in cupli's own scope (used
  when cupli itself does the substitution, e.g. in `composes:` lists).
* **Run `cupli space doctor` after edits** to catch validation errors
  with line numbers.

### MUST NOT

* **Don't put `container_name`, `networks`, or `depends_on`-from-cupli's-`deps:`
  into compose files manually.** Cupli generates them. Yours will get
  merged but is redundant.
* **Don't hardcode absolute paths.** Use `${APPS_PATH}/<name>` or
  `${<NAME>_APP_PATH}` instead.
* **Don't put `<NAME>_APP_PATH` into space's `vars:` manually.** Cupli
  generates these automatically for every declared component.
* **Don't edit files under `.locals/<space>/state/`.** They are
  regenerated and carry an `# AUTO-GENERATED by cupli. DO NOT EDIT`
  banner.
* **Don't put secrets in `vars:`.** They land in `override.env` which
  may be committed. Use `envs: [./.env.local]` and gitignore the file.
* **Don't change `mode: oneshot` to `mode: up` for migration / seeder
  tasks.** It changes the lifecycle semantics — `up` containers keep
  running, `oneshot` ones exit and block dependents on
  `service_completed_successfully`.

---

## Service binding cheat-sheet

### Form 1 — implicit (compose service name = app name)

```yaml
apps:
  postgres:
    composes: [ ./infra/postgres.compose.yml ]
```

Cupli binds to `services.postgres` in the compose file. Use when names
already match.

### Form 2 — string rename

```yaml
apps:
  redis:
    service: infra-redis          # compose service is named differently
    composes: [ ./compose.yml ]
```

Use when an existing compose-fragment ships a service whose name
doesn't equal your cupli app name.

### Form 3 — inline single-service (no compose file)

```yaml
apps:
  cache:
    service:
      image: redis:7-alpine
      command: [ "redis-server", "--appendonly", "yes" ]
      healthcheck:
        test: [ "CMD", "redis-cli", "ping" ]
        interval: 5s
      restart: unless-stopped
    vars:
      LOG_LEVEL: info             # injected as services.cache.environment
    ports:
      - "6379:6379"               # injected as services.cache.ports
```

Use when a single small service doesn't deserve its own compose file.
Any docker-compose attribute is valid inside `service: {...}`.

### Form 4 — multi-service map

```yaml
apps:
  backend:
    vars: { DATABASE_URL: ... }                # shared by every service below
    ports: [ "8000:8000" ]                      # default for primary; overridable below
    services:
      backend: # primary
        image: ${IMAGE}
        command: [ uvicorn, app.main:app ]
      celery-worker:
        image: ${IMAGE}
        command: [ celery, -A, app.tasks, worker ]
        depends_on: [ backend ]
        vars: { CELERY_LOG_LEVEL: info }        # per-service override (merge)
        ports: [ ]                              # opt out of inherited ports
      celery-beat:
        image: ${IMAGE}
        command: [ celery, -A, app.tasks, beat ]
        depends_on: [ backend ]
        ports: [ ]
```

Use for compound apps (web + workers + beat, api + sidecar). Each
service value can mix compose-syntax with cupli-only `vars` (merged
into app-level) and `ports` (replaces app-level when present).

### Form 4 — list shorthand

```yaml
apps:
  fleet:
    composes: [ ${ APP_PATH }/docker-compose.yml ]   # services declared in the compose-fragment
    services:
      - api
      - worker
      - beat
```

Equivalent to `services: {api: {}, worker: {}, beat: {}}`. Use when
each service in the compound app just inherits app-level `vars` /
`ports` with no per-service tweaks.

---

## Common edit patterns (prompts you'll see)

### "Add a celery worker"

If the app uses Form 1/2/3 → migrate to Form 4 (`services:` map),
moving the existing service spec into the map under the primary name.
Add the worker as another entry with `command: [celery, ...]` and
`depends_on: [<primary>]`.

### "Pin everything to branch X"

Add `branch: X` to every `apps.<name>` and `mounts.<name>` with `repo:`.
Then `cupli git checkout X` to switch existing working trees.

### "Add a one-off migration step"

```yaml
apps:
  migrate:
    repo: <same as backend>
    path: ${BACKEND_APP_PATH}     # share working tree with backend
    bases: [ python_runtime, pg_client ]
    deps:
      postgres: [ default ]
    mode: oneshot                 # exits when done; blocks dependents
    composes: [ ${ APP_PATH }/docker-compose.yml ]
```

Then add to dependents:

```yaml
apps:
  backend:
    deps:
      migrate: [ default ]          # backend waits for migrate to finish
```

### "Wait for a healthy dependency instead of just `started`"

`deps:` supports compose-style start conditions. The default is
``service_started`` (or ``service_completed_successfully`` for a
``mode: oneshot`` dep). Override with a string value (condition shorthand) or
a full ``DepSpec`` mapping:

```yaml
apps:
  api:
    deps:
      postgres: service_healthy            # wait for compose healthcheck to pass
      redis: ~                              # default: service_started
      mail: ~
      object-store: service_healthy
      init-data:
        condition: service_completed_successfully   # init container must exit cleanly
        restart: true                       # restart `api` when init-data restarts
        required: true                      # default; set false for a soft dep
```

Mode-tag list form (`worker: [default, hook]`) still works for ``--mode``
filtering — those two name spaces (``default``/``hook``/``full`` modes vs
``service_*`` conditions) don't collide. The full form lets you set
``modes`` alongside ``condition`` / ``restart`` / ``required`` in one place:

```yaml
    deps:
      worker:
        modes: [default, hook]
        condition: service_healthy
```

Cupli renders these straight into compose ``depends_on.<svc>``.

### "Share a SDK between two apps via mount"

```yaml
mounts:
  shared-sdk:
    repo: git@github.com:.../shared-sdk.git
    branch: main
    hosted_in: [ shop-web, shop-api ]
    exec_path: /opt/shared-sdk
    mode: rw
```

Toggle: `cupli mounts attach shared-sdk` / `cupli mounts detach shared-sdk`.

### "Let the IDE resolve a workspace library mounted under the app workdir"

Add `host_bridge: true` to a mount whose `exec_path` lives under the hosting
app's workdir bind (e.g. `${APP_PATH}:/app`). cupli maintains an inverse
host symlink — `<host-equivalent of exec_path> → mount.path` — so host
tooling (IDEs, workspace-package resolvers) sees the library at the same
relative path the container uses:

```yaml
mounts:
  web-ui-kit:
    hosted_in: [ web ]
    path: ${LIBS_PATH}/ui-kit
    exec_path: /app/packages/ui-kit
    host_bridge: true                 # auto-derive the host link from the workdir bind
    # or override:
    # host_bridge:
    #   link: ${WEB_APP_PATH}/packages/ui-kit   # explicit host link
    #   relative: true                           # relative symlink (default; portable)
```

- Created/repaired on `cupli up` and `cupli mounts attach`; removed on
  `cupli mounts detach`. Run explicitly with `cupli mounts bridge [names…]` /
  `cupli mounts unbridge [names…]`.
- cupli only touches symlinks it created (tracked in `state/bridges.json`).
  An empty directory or a 0-byte file stub on the link path (left by docker /
  a prior run) is reclaimed; a non-empty dir, a non-empty file, or a foreign
  symlink is left alone (`E032`, reported per-mount — one conflict never aborts
  the batch or `cupli up`).
- `host_bridge: true` auto-derives the link from the hosting app's workdir bind
  (`docker compose config`), scoped to that app's compose service(s) — so it
  works without an explicit `link:` in the common case. An explicit `link:`
  works offline and is exposed as `${<MOUNT>_BRIDGE_PATH}`.
- `cupli mounts list` shows a `bridge` column (`none`/`pending`/`ok`/
  `broken`/`conflict`).

### "Materialise node_modules on the host so the IDE resolves dependencies"

JetBrains/VS Code do not resolve JS dependencies through a remote (Docker)
Node interpreter, so `node_modules` must exist as real files on the host. The
`exports:` block copies a container-built directory (living in a named volume)
out to the host. **Export is for IDE indexing, not for running host tooling**
— the exported tree may carry native binaries for the image's libc, not the
host's.

```yaml
exports:
  web-node-modules:
    from: web                                   # the app (single) whose service owns it
    exec_path: /app/node_modules                # container source
    path: ${WEB_APP_PATH}/node_modules          # host destination
    strategy: sync                              # sync (default) | bind-seeded
    refresh_on: [ build ]                       # up | build | restart (default: [build])
    gitignore: true                             # add path to root .gitignore (default true)
```

- **`sync`** (default, recommended) — keeps the named volume for container
  I/O and copies it to the host one-way on each `refresh_on` event. Symlinks
  are preserved, so pnpm's `.pnpm` / `@scope/<lib>` structure survives.
- **`bind-seeded`** — turns `exec_path` into a host bind (injected into the
  generated post-override) seeded **offline from the image** (`docker cp`-style
  copy of `exec_path`, NOT a runtime `pnpm/uv install`), so the container writes
  straight to the host (always live). On a fresh `cupli up` the image is built
  first, so the seed copies real content rather than starting with an empty
  bind. Re-seeded from the new image on `refresh_on: [build]`.
- **Fresh `up` is race-safe:** before starting, cupli builds (when `--build` or
  an image needed below is missing), pre-initialises any named volume shared by
  ≥2 services of an app (one-shot, serial — avoids docker's concurrent
  volume-init race), then seeds bind-seeded exports.
- Lifecycle: seeded/refreshed automatically after `up` / `build` / `restart`
  per `refresh_on`; manually via `cupli exports sync [names…]`. Inspect with
  `cupli exports list` (`missing`/`stale`/`seeded`/`synced`); remove a `sync`
  host copy with `cupli exports clean [names…]`. Auto-vars `${EXPORT_PATH}` /
  `${EXPORT_EXEC_PATH}` / `${<NAME>_EXPORT_PATH}` are available in scope.
- Pair with `host_bridge` mounts: the relative symlinks inside `node_modules`
  (`@scope/<lib> → ../../packages/<lib>`) resolve on the host only when
  `packages/<lib>` is bridged too.
- **`.venv` caveat:** a Python remote (Docker Compose) interpreter resolves
  fine, so prefer it. A `.venv`-like export is **skipped** (`E034`) unless
  `rewrite_paths: true` is set — editable installs write absolute container
  paths (`/app/...`) that don't exist on the host, so a naive sync is useless.
  `rewrite_paths: true` (experimental) syncs and rewrites the workdir prefix
  (`/app/...` → the app's host path) in `.pth` / `.egg-link` files.

### "Add a top-level command for linting"

```yaml
commands:
  lint:
    container: backend           # app name (NOT compose service name)
    run: ruff check src tests
    help: Lint the backend.
    top_level: true              # `cupli lint` works alongside `cupli sc lint`
```

### "Add a command with arguments / grouping / multiple containers"

`commands:` entries support more than a fixed `run`. Use these when a
shortcut needs parameters, a help panel, several steps, or several
containers:

```yaml
commands:
  db-migrate:
    group: Database              # groups the command under a "Database" help panel
    container: backend           # one app, or a list: [backend, worker]
    args:                        # typed params shown in `cupli db-migrate --help`
      - name: app                #   required positional: `cupli db-migrate users`
        help: App label to migrate.
        required: true
      - name: fake               #   bool -> a `--fake` flag (bool is always an option)
        type: bool
        help: Record without applying.
      - name: verbosity          #   `--verbosity` / `-v`, typed int with a default
        option: true
        short: v
        type: int
        default: 1
    run: python manage.py migrate {{app}} {{fake}} --verbosity {{verbosity}}
    top_level: true

  pip-check:
    container: [backend, worker] # runs in each listed app's service
    execute: parallel            # sequential (default, fail-fast) | continue | parallel
    run: pip list --outdated
```

Rules for `commands:`:

* **`container`** — one app name or a list. A list runs the command in every
  listed app's primary service; **`execute`** picks the strategy:
  `sequential` (default, stops at the first failure), `continue` (run all,
  non-zero exit if any failed), or `parallel` (concurrent, output captured
  per container).
* **`run`** — a single line, a YAML block scalar, or a list of lines (joined
  with newlines). It runs via `sh -c`, so `&&`, `|`, `$VAR` work. A multi-line
  script is **not** fail-fast by default — chain with `&&` or start with
  `set -e` if you need that.
* **`args`** — declared, typed parameters. Each has `name`, optional `help`,
  `type` (`str`/`int`/`bool`), `option` (positional vs `--flag`), `short`
  (option alias), `required`, `default` (mutually exclusive with `required`).
  A `bool` is always a flag. Reference each in `run` via `{{name}}`; values are
  shell-quoted automatically. A bare list — `args: [path, name]` — is shorthand
  for required positional string args. Arg names must be valid identifiers
  (letters, digits, `_`; no `-`).
* **`group`** — label that becomes a help panel for top-level commands and
  groups the `cupli sc` listing.
* **`strict`** — when False (default), CLI tokens not matching a declared `arg`
  (flags and positionals) are forwarded verbatim to the end of the command, so
  `cupli sc deploy prod --force-recreate` runs `deploy prod --force-recreate`.
  Set `strict: true` to reject unknown tokens instead. Without any `args`, a
  single-line `run` still gets `"$@"` appended so `cupli sc test -k foo`
  forwards extra tokens.
* Every command is reachable as `cupli sc <name>` (resolved live from the
  active space, so it works with `-f` / `-s` and a cold cache); `top_level:
  true` ALSO promotes it to a `cupli <name>` verb. Both forms parse the typed
  `args`, show them in `--help`, and tab-complete.

Builtin compose verbs (`cupli up`, `down`, `build`, `pull`, `stop`, `restart`,
`ps`, `logs`) also forward unknown flags to docker compose — e.g.
`cupli up --force-recreate`. Use the `--opt=value` form for value-taking flags
so the value is not read as a service name.

### "Declare a named volume / build secret for an inline service"

Top-level `volumes:` / `secrets:` / `configs:` are merged verbatim into the
generated pre-override, so an inline service can reference them without a
separate compose file:

```yaml
volumes:
  db_data:                       # null body == default-driver named volume

apps:
  db:
    service:
      image: postgres:16
      environment:
        POSTGRES_PASSWORD: ${DB_PASSWORD}
      volumes: [ db_data:/var/lib/postgresql/data ]   # references the named volume above
```

---

## How cupli evaluates a space file (so you understand what's possible)

1. **Parse YAML** with ruamel for line/col tracking.
2. **Validate** against `SpaceModel` (Pydantic). Failure → `E002`
   with per-field `file:line:col`.
3. **Resolve space scope** — `auto-vars` + `<NAME>_*_PATH` defaults +
   `envs:` files + `vars:` (in order, later wins).
4. **Resolve bases** in C3 linearisation order, each producing its own
   resolved scope.
5. **Resolve apps** — each app picks its base chain, merges scopes,
   substitutes `${VAR}` everywhere.
6. **Resolve mounts** — analogously.
7. **Render overrides** into `.locals/<space>/state/`.
8. **`docker compose` invocation** with `COMPOSE_FILE` chaining:
   `pre → bases.composes → apps.composes → inline → post`.

---

## Tools you have available

Run these to verify your edits:

```bash
cupli space doctor              # validate the whole space (path checks etc.)
cupli config                    # print merged docker-compose config
cupli graph                     # tree of bases/apps/mounts/commands
cupli env                       # full resolved env-file
cupli env -c <app>              # an app's resolved scope
cupli mounts list               # mounts + host_bridge status
cupli mounts bridge / unbridge  # create / remove host_bridge symlinks
cupli exports list              # exports + materialisation status
cupli exports sync / clean      # materialise / remove host copies
cupli --strict-vars <cmd>       # promote ${UNKNOWN} warnings to errors
cupli -V                        # version (script-friendly)
```

When something fails, the error has a numbered code:

```
E002 Validation failed
  /path/to/space.cupli.yaml: 1 error(s)
  • apps.api.mode: Input should be 'up', 'oneshot' or 'disabled' (...:6:5)
  hint: Fix the fields listed above (each entry includes file:line:col when known).
```

`cupli explain <code>` for the full reference.

---

## Error codes you'll meet most

| Code   | Cause                                  | Fix                                                                                                                                                                                                                       |
|--------|----------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `E001` | Space file not found.                  | Check path.                                                                                                                                                                                                               |
| `E002` | Validation.                            | Read per-field messages — they include line numbers.                                                                                                                                                                      |
| `E014` | `${VAR}` cycle.                        | Break the cycle.                                                                                                                                                                                                          |
| `E015` | User var shadows reserved name.        | Rename the var or pass `--allow-shadow`.                                                                                                                                                                                  |
| `E016` | Unknown `${VAR}` in strict mode.       | Define the var or remove the reference.                                                                                                                                                                                   |
| `E017` | `git clone` failed.                    | Check repo URL, branch, SSH access.                                                                                                                                                                                       |
| `E020` | Unknown name.                          | Check spelling against `cupli --list` or `cupli graph`.                                                                                                                                                                   |
| `E029` | Space file already exists.             | `cupli init --force` to overwrite.                                                                                                                                                                                        |
| `E030` | Per-component env-var name collision.  | Rename one of the components (`shop-api` and `shop_api` both → `SHOP_API_APP_PATH`).                                                                                                                                      |
| `E031` | Planned service not declared anywhere. | Either add it to a compose-fragment listed under `composes:` (and run `cupli space sync` if the repo isn't cloned yet), or supply at least one inline compose field (e.g. `image:`) under `service:` / `services.<name>`. |
| `E032` | Host path for a bridge/export holds a non-empty dir, a file, or a foreign symlink. | Move/remove it, or `cupli exports clean` / `cupli mounts unbridge` if cupli made it. (Empty dirs are reclaimed automatically; cupli never overwrites non-empty/foreign objects.) |
| `E033` | Could not chown a materialised export to the host user. | Fix permissions on the host path (no root-owned parents from an earlier docker run), then re-sync. |
| `E034` | A `.venv`-like export is skipped (editable installs carry absolute container paths). | Prefer a remote Python interpreter; or set `rewrite_paths: true` (experimental) to sync and rewrite those paths. |

---

## Idioms

* `${REGISTRY}/<app>:<tag>` — image name templates.
* `${APPS_PATH}/<name>` or `${<NAME>_APP_PATH}` — refer to a sibling app's path.
* `${USER_ID:-1000}` — fall-back for envs that might not be set.
* `depends_on: [<service-name>]` — plain compose syntax inside an
  inline service spec. NOT to be confused with cupli's
  `apps.<name>.deps:` which is at the app level (across apps).

---

## Things to remember if you're tempted to "fix" something

* **`override.*.yml` files in `.locals/` are generated.** Don't edit
  them. Edit `space.cupli.yaml` and re-run cupli.
* **Sub-mount placeholders on the host are pre-created by cupli.** Before
  ``cupli up`` / ``build`` / ``run`` / ``watch`` cupli resolves the merged
  compose config and creates host paths for every mount whose container target
  sits under a bind target (e.g. a named volume `/app/.venv` under a bind
  `${APP_PATH}:/app`). They are created **as the cupli user**, so the docker
  daemon does not create them as root. The placeholders are empty dirs (or a
  touched file when the sub-mount binds a single file); they are safe to
  delete and will be recreated.

  **File placeholders are created read-only on the host.** The empty 0-byte
  file is only a mount point — docker overlays the bind source on top, and the
  container sees the real content. The host file stays empty by design and is
  ``chmod 0o444`` so IDEs and humans don't try to edit it. Docker mount
  ignores host perms, so the running container is unaffected.

* **Cupli changes that affect mounts only apply to NEWLY created containers.**
  After upgrading cupli (or changing the workspace's mount / compose layout),
  recreate running containers with ``cupli restart --hard`` (or ``cupli down
  && cupli up -d``). The mount-target prep step runs before each ``up``, but
  it cannot re-mount inside a container that is already running.
* **A pinned `branch:` does NOT auto-switch the working tree.** Cupli
  reports drift; you opt in to switch via `cupli git checkout`.
* **`vars:` at app-level land in `environment:` of every service the
  app drives**, plus the env-file. Don't repeat them in compose-syntax
  `environment:` — you'll create duplicates (harmless but noisy).
* **`ports: []` is explicit "no ports"**, not "default ports". It opts
  out of inherited app-level `ports`.
* **`service: dict` and `services: map` are mutually exclusive.** Pick
  one. If you migrate from `service: dict` to `services:`, move the
  whole compose spec under the new entry whose key = the desired
  compose service name.
* **`cupli up <name>` accepts both app names and individual compose-service
  names from compound apps.** Targeting `cupli up celery-worker` starts
  only that one service (without firing up `celery-beat` and `backend`).
* **Per-service verbs do NOT pull in `apps[*].deps`.** `cupli restart api`,
  `stop`, `down`, `ps`, `build`, `pull` act exactly on what was named — the
  databases / queues / caches the app depends on stay as they are. Only
  `cupli up` walks the closure (deps must be started first). The
  workspace-wide forms (`cupli restart` / `cupli stop` / `cupli down` with
  no arguments) and tag-filtered forms (`--tag api`) still operate on the
  whole selected set. So:
  - `cupli restart api` → bounces only `api`.
  - `cupli restart` → bounces every service in the workspace.
  - `cupli down api` → removes only the `api` container.
  - `cupli down` (no args) → removes every container the workspace owns.
* **`cupli up --mode <m>` filters cross-app deps.** Without it, deps
  inclusion follows the universe (all active apps). With a mode, only
  deps whose mode-list contains `<m>` are walked.

---

## Where to look for more

* `space.cupli.yaml` at repo root — full reference with comments on
  every key.
* `docs/examples/{minimal,celery,multi-repo-shop,full-reference}/` — worked
  examples by complexity.
* `README.md` / `README.ru.md` — user-facing docs.
* `cupli --list` — every CLI command grouped by area.
* `cupli explain <code>` — error code lookup.
