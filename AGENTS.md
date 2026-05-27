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
├─ mounts:            toggleable bind-mounts (cupli mounts attach/detach)
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
* `docker-compose.post.yml` — `environment` / `ports` / `volumes` /
  `depends_on` / `networks` injection.

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
    service: agora-redis          # compose service is named differently
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
  minio_data:                    # null body == default-driver named volume

apps:
  minio:
    service:
      image: minio/minio
      command: server /data
      volumes: [ minio_data:/data ]   # references the named volume above
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
* **`cupli up --mode <m>` filters cross-app deps.** Without it, deps
  inclusion follows the universe (all active apps). With a mode, only
  deps whose mode-list contains `<m>` are walked.

---

## Where to look for more

* `space.cupli.yaml` at repo root — full reference with comments on
  every key.
* `examples/{minimal,celery,multi-repo-shop,full-reference}/` — worked
  examples by complexity.
* `README.md` / `README.ru.md` — user-facing docs.
* `cupli --list` — every CLI command grouped by area.
* `cupli explain <code>` — error code lookup.
