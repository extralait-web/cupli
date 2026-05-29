<p align="center">
  <img src="docs/resources/brand.svg" width="100%" alt="cupli">
</p>
<p align="center">
    <em>Multi-repository docker-compose workspace orchestrator. One YAML, one `cupli up`, every container running.</em>
</p>

<p align="center">

<a href="https://github.com/extralait-web/cupli/actions?query=event%3Apush+branch%3Amaster+workflow%3ACI" target="_blank">
    <img src="https://img.shields.io/github/actions/workflow/status/extralait-web/cupli/ci.yml?branch=master&logo=github&label=CI" alt="CI">
</a>
<a href="https://pypi.python.org/pypi/cupli" target="_blank">
    <img src="https://img.shields.io/pypi/v/cupli.svg" alt="pypi">
</a>
<a href="https://pepy.tech/project/cupli" target="_blank">
    <img src="https://static.pepy.tech/badge/cupli/month" alt="downloads">
</a>
<a href="https://github.com/extralait-web/cupli" target="_blank">
    <img src="https://img.shields.io/pypi/pyversions/cupli.svg" alt="versions">
</a>
<a href="https://github.com/extralait-web/cupli/blob/master/LICENSE" target="_blank">
    <img src="https://img.shields.io/github/license/extralait-web/cupli.svg" alt="license">
</a>

</p>

> 🇷🇺 [README на русском](README.ru.md)

`cupli` is for projects where each component (backend, frontend,
worker, shared SDK, infra) lives in its **own git repository** but the
whole stack needs to come up on one machine with one command. It builds
on `docker compose` without replacing it.

* **Spec-first.** One `space.cupli.yaml` declares everything: repos,
  bases, mounts, services, shortcuts.
* **Inline or external compose.** Define services in YAML directly, or
  point at an existing `docker-compose.yml`. Mix freely.
* **Multi-repo git.** `cupli git status / pull / fetch / checkout`
  operate across every cloned component in parallel, with per-repo
  selectors and per-repo branch maps.
* **Variable scope.** Space → bases (C3) → app, with `${VAR}` and
  `${VAR:-default}` interpolation everywhere.
* **Branch pinning + drift.** `branch: main` on a component is honoured
  by `cupli init` (`git clone -b`) and surfaced in `cupli git status`
  when the working tree drifts off.
* **Mount toggling.** `cupli mounts attach <name>` bind-mounts a shared
  SDK into N containers without YAML edits.
* **Shell completion** for every name (apps, services, mounts, tags,
  shortcuts, error codes).

> 🤖 **Using an AI agent to edit `space.cupli.yaml`?** Point it at
> [`AGENTS.md`](AGENTS.md) — a self-contained guide to the schema, service
> binding, `commands:`, top-level blocks, and error codes.

---

## Table of contents

1. [Install](#install)
2. [Quick-start](#quick-start)
3. [Concepts](#concepts)
4. [The `space.cupli.yaml` reference](#the-spacecupliyaml-reference)
5. [CLI reference](#cli-reference)
6. [Recipes](#recipes)
7. [IDE setup](#ide-setup)
8. [Limitations](#limitations)
9. [Troubleshooting + error codes](#troubleshooting--error-codes)

---

## Install

```bash
uv tool install cupli                 # recommended
# or
pipx install cupli
# or
pip install --user cupli
```

Verify:

```bash
cupli -V                              # cupli 0.1.0  (script-friendly)
cupli --version                        # full info: python, platform, deps
```

Cupli requires Python ≥ 3.10. Docker / `docker compose` must be on PATH.

### Shell completion

One-shot, picks your shell automatically from `$SHELL`:

```bash
cupli completion install
```

Or pin the shell:

```bash
cupli completion install --shell bash      # bash | zsh | fish | pwsh
cupli completion show --shell zsh > ~/.zsh/completions/_cupli
```

---

## Quick-start

```bash
mkdir my-workspace && cd my-workspace
cupli init --name my-workspace                # scaffolds space.cupli.yaml + .env + .locals/
$EDITOR space.cupli.yaml                       # describe your apps
cupli up                                       # build + start everything
cupli ps                                       # see what's running
cupli logs my-api -f
cupli down                                     # tear down
```

The smallest possible workspace:

```yaml
# space.cupli.yaml
schema_version: 1
name: hello

apps:
  cache:
    service:                                   # inline compose-spec
      image: redis:7-alpine
      command: ["redis-server", "--appendonly", "yes"]
    ports: ["6379:6379"]
```

```bash
cupli up
cupli exec -c cache -- redis-cli ping        # PONG
```

See [`docs/examples/minimal/`](docs/examples/minimal/) for the same workspace with comments.

---

## Concepts

### Space

A **space** is the unit cupli operates on — one `space.cupli.yaml`,
one project, one docker-compose project. Spaces have a `name:`, which
also doubles as the docker-compose project name and the default network
name.

### App

An **app** is what cupli starts and stops. Each app binds to one or
more docker-compose services. The binding is declared one of four ways:

1. Implicit — service name equals app name.
2. `service: "name"` — bind to an existing compose service by name.
3. `service: {image: ..., command: ..., ...}` — *inline* single-service
   spec, no separate compose file.
4. `services: { name1: {...}, name2: {...} }` — compound app with
   multiple compose services (think: api + celery workers + beat).

In forms 3 and 4 the dict accepts **any** docker-compose service
attribute (`image`, `build`, `command`, `environment`, `depends_on`,
`healthcheck`, `volumes`, `restart`, …). Cupli reserves `vars` and
`ports` for its own injection logic; everything else is passed through
to docker-compose verbatim via a generated `docker-compose.inline.yml`.

### Base

A **base** is a reusable template. Apps cite bases via
`bases: [name1, name2]` and inherit `vars:`, `envs:`, `composes:`,
`repo:` from them in C3 linearisation order. Bases keep boilerplate
DRY across apps that share runtime.

### Mount

A **mount** is a host-to-container bind that toggles on/off without
editing YAML. Useful for hot-swapping a vendored SDK to a local
checkout. `cupli mounts attach/detach <name>` flips the state.

### Host resolution for IDEs (`host_bridge` & `exports`)

IDEs index the **host** filesystem, while cupli runs everything inside
containers. Two opt-in features bridge that gap (both are off by default and
exist purely for editor resolution — never for running host tooling):

* **`host_bridge`** on a mount keeps an inverse host symlink
  (`<host-equivalent of exec_path> → mount.path`) so a library mounted under
  the app workdir is visible on the host at the same relative path the
  container uses. Lifecycle-managed (`up` / `mounts attach`/`detach`) or
  explicit via `cupli mounts bridge` / `unbridge`.
* **`exports`** copies a container-built directory (typically a named volume
  like `node_modules`) onto the host. `strategy: sync` (default) mirrors the
  volume on `refresh_on` events; `strategy: bind-seeded` turns the path into a
  live host bind. Manage with `cupli exports sync` / `clean`.

They compose: pnpm's relative symlinks inside an exported `node_modules`
(`@scope/<lib> → ../../packages/<lib>`) resolve on the host only when
`packages/<lib>` is bridged. There's an asymmetry between stacks — a JS remote
(Docker) interpreter does **not** resolve dependencies, so `node_modules` must
exist on the host; a Python remote interpreter resolves fine, so prefer it over
exporting `.venv` (a `.venv` export is skipped unless `rewrite_paths: true`).
See the [`exports.<name>`](#exportsname) reference for fields.

### Service

A **service** in cupli is exactly what docker-compose calls a service —
a container declaration. Apps own services; one app may own many.

### Workspace registry

Spaces register themselves in `~/.config/cupli/spaces.json` so you can
operate by name from anywhere:

```bash
cupli workspace add -n shop -f ~/work/shop/space.cupli.yaml
cupli -s shop up
cupli workspace select shop                 # sticky: subsequent cupli calls target shop
cupli workspace unselect                    # back to cwd-detect
```

---

## The `space.cupli.yaml` reference

The full reference is [`space.cupli.yaml`](space.cupli.yaml) at the
repo root and copied to
[`docs/examples/full-reference/`](docs/examples/full-reference/). Below is the
schema with one-line descriptions.

### Top level

| Key | Type | Default | What it does |
|---|---|---|---|
| `schema_version` | int | — | Version pin. Only `1` is supported. |
| `name` | string | — | Project identifier. Used as docker-compose project name and default network name. Matches `^[A-Za-z][A-Za-z0-9_-]*$`. |
| `cupli_min` / `cupli_max` | string \| `"*"` | — | Tool-version guards. |
| `extends` | string | — | Path to a parent space (one level only in v1). |
| `envs` | list[string] | `[]` | `.env` files loaded into space scope, before `vars`. |
| `vars` | map[str, str] | `{}` | Space-scope variables; visible everywhere; written to `override.env` for docker-compose substitution. |
| `bases` | map[str, base] | `{}` | Reusable templates. |
| `apps` | map[str, app] | `{}` | Run units. |
| `mounts` | map[str, mount] | `{}` | Toggleable bind-mounts. |
| `exports` | map[str, export] | `{}` | Materialise container-built dirs (`node_modules`) onto the host for IDE resolution. |
| `hooks` | map[str, hook-override] | `{}` | Per-target tweaks for `cupli hooks install`. |
| `commands` | map[str, command-shortcut] | `{}` | `cupli sc <name>` / `cupli <name>` (with `top_level: true`). |
| `networks` | map[str, dict] | `{}` | Top-level docker-compose `networks:` block. Values are compose-spec verbatim (`driver`, `name`, `ipam`, etc.). Cupli's `default` network is merged in automatically. |
| `volumes` | map[str, dict] | `{}` | Top-level docker-compose `volumes:` block. Named volumes (compose-spec verbatim) so inline services can reference them without a separate compose file. A null body (`minio_data:`) is a default-driver volume. |
| `secrets` | map[str, dict] | `{}` | Top-level docker-compose `secrets:` block. Secret definitions (compose-spec verbatim) referenced by service-level `secrets:`. |
| `configs` | map[str, dict] | `{}` | Top-level docker-compose `configs:` block. Config definitions (compose-spec verbatim) referenced by service-level `configs:`. |

### `bases.<name>`

| Key | Type | Default | What it does |
|---|---|---|---|
| `path` | string | `${BASES_PATH}/<name>` | On-disk location. |
| `repo` | string | — | Git URL (omit for an in-place base). |
| `branch` | string | — | Branch to clone (`git clone -b <branch>`). |
| `post_clone` | string | — | Shell command run on host after a successful clone. |
| `init_vars` | map | `{}` | Env exported to clone + `post_clone`. |
| `vars` | map | `{}` | Variables contributed to inheriting apps. |
| `envs` | list[string] | `[]` | Env files loaded into the base scope. |
| `composes` | list[string] | `[]` | Compose-fragments prepended to inheriting apps' `COMPOSE_FILE` chain. |

### `apps.<name>`

| Key | Type | Default | What it does |
|---|---|---|---|
| `path` | string | `${APPS_PATH}/<name>` | On-disk location. |
| `repo` | string | — | Git URL. |
| `branch` | string | — | Branch to clone. `cupli git status` flags drift. |
| `post_clone` | string | — | Shell command run on host after clone. |
| `init_vars` | map | `{}` | Env exported to clone + `post_clone`. |
| `bases` | list[string] | `[]` | Bases to inherit (C3 multi-inherit). |
| `deps` | list[str] \| map[str, …] | `{}` | Cross-app `depends_on`. List form `[a, b]` or map with per-dep settings (mode tags for `--mode` filtering, compose condition / restart / required). See [Dependency conditions](#dependency-conditions). |
| `tags` | list[string] | `[]` | For `cupli up --tag <tag>`. |
| `mode` | enum | `up` | `up` (long-running), `oneshot` (run-once), `disabled`. |
| `composes` | list[string] | `[]` | External compose files. |
| `service` | string \| dict | — | Single-service binding. Dict form is inline compose-spec. |
| `services` | map[str, dict] \| list[str] | — | Multi-service map (each value is a compose-spec with optional cupli-only `vars` and `ports`) or a bare list of service names (equivalent to a map with empty overrides). Mutually exclusive with `service`. |
| `vars` | map | `{}` | Variables; injected as `environment` on every managed service. |
| `envs` | list[string] | `[]` | Env files loaded into app scope. |
| `ports` | list[string] | `[]` | Compose-style port mappings; injected into the app's primary service (or every service in `services:`). |
| `forward_ssh` | bool | `false` | Mount `$SSH_AUTH_SOCK` into the container. |

#### Service binding forms — all four are valid

```yaml
# 1) implicit (service name = app name)
apps:
  api: {}

# 2) string (rename binding)
apps:
  redis:
    service: cache-redis        # bind to compose service `cache-redis`
    composes: [./compose.yml]

# 3) inline single-service (any compose attribute is fair game)
apps:
  cache:
    service:
      image: memcached:1.6
      command: ["memcached", "-m", "64"]
      healthcheck: {test: ["CMD", "echo", "stats", "|", "nc", "localhost", "11211"]}
    vars: {LOG_LEVEL: info}
    ports: ["11211:11211"]

# 4) services map (one app, N compose services)
apps:
  backend:
    vars: {DATABASE_URL: ...}   # shared with every service below
    services:
      backend:
        image: ${IMAGE}
        command: [uvicorn, app.main:app]
      celery-worker:
        image: ${IMAGE}
        command: [celery, -A, app.tasks, worker]
        vars: {CELERY_LOG_LEVEL: info}    # per-service override (merged)
        ports: []                          # explicit empty: opt out of app-level ports

# 4b) services as a bare list — same as `{name: {}}` for each
apps:
  fleet:
    composes: [${APP_PATH}/docker-compose.yml]
    services:
      - api
      - worker
      - beat
```

> `${VAR}` inside inline compose-spec (`service.build.context: ${APP_PATH}`)
> is substituted by docker-compose, not cupli — use `${<APP_NAME>_APP_PATH}`
> (per-component path-var, which cupli writes into `override.env`) when you
> need the path of a specific app. Bare `${APP_PATH}` only resolves where
> cupli does the substitution itself (e.g. `composes:`).

### `mounts.<name>`

| Key | Type | Default | What it does |
|---|---|---|---|
| `path` | string | `${MOUNTS_PATH}/<name>` | Host source dir. |
| `repo` | string | — | Git URL. |
| `branch` | string | — | Branch to clone. |
| `post_clone` | string | — | After-clone host command. |
| `hosted_in` | list[string] | required | App names whose every service gets the bind. |
| `exec_path` | string | required | Absolute POSIX path inside container. |
| `mode` | enum | `rw` | `rw` \| `ro`. |
| `mac_volume` | enum | — | macOS volume consistency hint. |
| `host_bridge` | bool \| map | `false` | Maintain an inverse host symlink so host tooling (IDEs) sees the mount at the container-relative path. `true` auto-derives the link from the hosting app's workdir bind; a map (`{link, relative}`) overrides it. See [host_bridge & exports](#host-resolution-for-ides-host_bridge--exports). |
| `envs` | list[string] | `[]` | Env files. |
| `vars` | map | `{}` | Variables. |

### `exports.<name>`

Materialise a directory built inside a container (typically a named volume
such as `node_modules`) onto the host so IDEs that only resolve from the local
filesystem can index it. **For IDE indexing, not for running host tooling** —
exported native binaries may target the image's libc, not the host's.

| Key | Type | Default | What it does |
|---|---|---|---|
| `from` | string | required | App (single) whose service owns the source directory. |
| `exec_path` | string | required | Absolute POSIX source path inside the container. |
| `path` | string | required | Host destination path (`${VAR}` resolved in scope). |
| `strategy` | enum | `sync` | `sync` (keep the named volume, copy to host on `refresh_on`) or `bind-seeded` (turn `exec_path` into a host bind seeded from the image — always live). |
| `refresh_on` | list[enum] \| string | `[build]` | Lifecycle events that re-materialise the export: `up`, `build`, `restart`. |
| `gitignore` | bool | `true` | Add `path` to the root `.gitignore` (under a `# cupli exports` section). |
| `mac_volume` | enum | — | macOS volume consistency hint. |
| `rewrite_paths` | bool | `false` | Experimental: sync a `.venv`-like export anyway and rewrite absolute container paths (`/app/...`) in `.pth` / `.egg-link` files to host equivalents. Without it, a `.venv`-like export is skipped (`E034`). |

### `commands.<name>`

| Key | Type | Default | What it does |
|---|---|---|---|
| `container` | string \| list[string] | required | App name(s) whose primary service runs the command. A list runs it in each. |
| `run` | string \| list[string] | required | Shell command line. A block scalar or list of lines is joined with newlines and run via `sh -c`. `{{name}}` placeholders are filled from `args`. |
| `workdir` | string | — | Working directory inside the container. |
| `help` | string | — | Short help shown in `cupli --help`. |
| `top_level` | bool | `false` | When true, also exposes as `cupli <name>` (alongside `cupli sc <name>`). |
| `group` | string | — | Label; groups the command under a panel in `cupli --help` and the `cupli sc` listing. |
| `execute` | enum | `sequential` | For a multi-container command: `sequential` (fail-fast), `continue` (run all, non-zero if any failed), or `parallel`. |
| `args` | list[arg] | `[]` | Declared, typed parameters surfaced in `cupli <cmd> --help` and substituted into `run` via `{{name}}`. A bare list of names is shorthand for required positional string args. |
| `strict` | bool | `false` | When false, CLI tokens not matching a declared `arg` (flags + positionals) are forwarded to the end of the command; when true, unknown tokens are rejected. |

#### `commands.<name>.args[]`

| Key | Type | Default | What it does |
|---|---|---|---|
| `name` | string | required | Identifier; the `{{name}}` placeholder and CLI arg/option name. |
| `help` | string | — | Description shown in `cupli <cmd> --help`. |
| `type` | enum | `str` | `str`, `int`, or `bool`. A `bool` is always an option (flag). |
| `option` | bool | `false` | When true, a `--name` option; otherwise a positional argument. |
| `short` | string | — | Single-letter alias for an option (`l` → `-l`). |
| `required` | bool | `false` | Whether the value must be supplied. Mutually exclusive with `default`. |
| `default` | string | — | Value substituted when the parameter is omitted. |

```yaml
commands:
  db-migrate:
    group: Database                 # `cupli --help` shows it under a "Database" panel
    container: api
    run: python manage.py migrate {{app}} {{fake}}
    args:
      - name: app                   # required positional: `cupli db-migrate users`
        required: true
        help: Django app label.
      - name: fake                  # bool -> a `--fake` flag
        type: bool
    top_level: true

  pip-freeze:
    container: [api, worker]        # run in several services
    execute: parallel               # sequential (default) | continue | parallel
    run: pip freeze
```

For a multi-line script, use a block scalar (newline-separated commands; add
`&&` or `set -e` for fail-fast within the script):

```yaml
  setup:
    container: api
    run: |
      python manage.py migrate
      python manage.py loaddata initial
```

### Auto-vars (always interpolatable)

* **Space scope** — `SPACE_NAME`, `SPACE_PATH`, `APPS_DIR`,
  `APPS_PATH`, `BASES_DIR`, `BASES_PATH`, `MOUNTS_DIR`, `MOUNTS_PATH`,
  `LOCALS_DIR`, `LOCALS_PATH`, `NETWORK`, `COMPOSE_PROJECT_NAME`.
* **Per-component** — `<NAME>_APP_PATH` for every app,
  `<NAME>_BASE_PATH` for every base, `<NAME>_MOUNT_PATH` for every
  mount, `<NAME>_EXPORT_PATH` for every export. Name is upper-cased with
  `-` mapped to `_`. Visible in YAML AND in `override.env`. A mount with an
  explicit `host_bridge.link` also exposes `<NAME>_BRIDGE_PATH`.
* **App / base** — `APP_NAME`, `APP_PATH`, `APP_LOCAL_PATH` (apps only).
* **Mount** — `MOUNT_NAME`, `MOUNT_PATH`, `MOUNT_HOST`, `MOUNT_EXEC_PATH`.
* **Export** — `EXPORT_NAME`, `EXPORT_PATH`, `EXPORT_EXEC_PATH`.

Default paths: `APPS_PATH` = `$SPACE_PATH/src/apps`, similarly for
bases and mounts. Override per-component with an explicit `path:`.

### Interpolation rules

* `${VAR}`, `${VAR:-literal-default}`, and bare `$VAR` are all recognised.
  `$$` escapes a literal `$` (docker-compose convention).
* Nested `${...}` inside a default is **not** supported. The default is
  literal.
* Cycles raise `E014`.
* Unknown vars resolve to `""` with a yellow warning. Pass
  `--strict-vars` to make them hard errors (`E016`).
* Shadowing a reserved auto-var name raises `E015` unless
  `--allow-shadow` is passed.

---

## CLI reference

`cupli --help` lists everything. Highlights:

### Lifecycle

| Command | What |
|---|---|
| `cupli up [services] [--tag t] [--mode m] [--build] [--pull p]` | `docker compose up`. Service args can be app names OR individual compose-service names from a compound app's `services:` map. |
| `cupli stop [services] [--tag t]` | `docker compose stop`. |
| `cupli restart [services] [--tag t] [--hard]` | restart, or down+up with `--hard`. |
| `cupli down [-v] [--images]` | `down --remove-orphans`, optional volumes + images. |
| `cupli ps [--tag t]` | running services table. |
| `cupli logs [service] [-f]` | per-service or all. |
| `cupli build [services] [--tag t]` | build images. |
| `cupli pull [services] [--tag t]` | pull images. |
| `cupli compose -- <args>` | pass-through to `docker compose`. |
| `cupli config` | merged compose configuration. |
| `cupli watch [services]` | `docker compose watch` — for `develop.watch` declared on a service. |

`--mode default|hook|full` filters cross-app `deps:` by their declared
mode-list. Use it to express dev-vs-prod-style dependency sets:
`api: {deps: {redis: [default, full]}}` pulls redis on both modes;
`audit: {deps: {redis: [full]}}` skips it under `--mode default`.

### Dependency conditions

`deps:` accepts compose-style start conditions per dependency. Default is
`service_started` (or `service_completed_successfully` for a `mode: oneshot`
dep). String value = condition shorthand; null = defaults; list = mode tags
(back-compat with `--mode` filtering); mapping = full spec.

```yaml
apps:
  api:
    deps:
      postgres: service_healthy             # wait for healthcheck
      redis: ~                              # default: service_started
      init-data:
        condition: service_completed_successfully
        restart: true                       # restart api when init-data restarts
        required: false                     # api still starts if init-data can't
```

These map straight onto compose `depends_on.<svc>.{condition,restart,required}`.

### Exec / run

| Command | What |
|---|---|
| `cupli exec -c <service> -- <cmd>` | run inside a running container. |
| `cupli run -c <service> -- <cmd>` | one-shot container (`run --rm`). |
| `cupli shell -c <service>` | open `/bin/bash` (override with `--shell`). |
| `cupli wrap -c <app> -- <cmd>` | run on the host with the app's env exported. |
| `cupli env [-c <app>] [--export]` | print resolved env. |

### Shortcuts

| Command | What |
|---|---|
| `cupli sc` | list declared `commands:`. |
| `cupli sc <name> [args]` | run shortcut. |
| `cupli <name>` | same shortcut when `top_level: true`. |

### Workspace

| Command | What |
|---|---|
| `cupli init [-n name] [--path .] [--force] [--no-sync] [--no-ide]` | scaffold + register. Creates `space.cupli.yaml`, `.env`, `.locals/`; `src/apps/`, `src/bases/`, `src/mounts/` are created lazily by `cupli space sync` when a declared component first needs them. |
| `cupli workspace add -n <name> -f <file>` | register an existing space. |
| `cupli workspace list` | every registered space with `*` on the active one. |
| `cupli workspace select <name>` | sticky active selection. |
| `cupli workspace unselect` | clear it (cwd-detect resumes). |
| `cupli workspace current` | what would be targeted right now. |
| `cupli workspace remove <name>` | drop from registry (filesystem untouched). |
| `cupli space sync [--apps/--bases/--mounts] [--pull]` | clone declared repos + optional pull. |
| `cupli space doctor [--strict]` | validate paths + repos. |

### Git (across every cloned component)

| Command | What |
|---|---|
| `cupli git status [targets]` | status table. Flags `drifted` when working tree branch ≠ pinned. |
| `cupli git pull [targets] [--rebase]` | parallel pull. |
| `cupli git fetch [targets]` | parallel fetch. |
| `cupli git checkout <branch> [-t target] [-m name=branch]` | branch switch with per-repo overrides. |

### Mounts

| Command | What |
|---|---|
| `cupli mounts list` | every declared mount and its state (incl. `host_bridge`). |
| `cupli mounts attach <name>` | bind-mount into `hosted_in` apps. |
| `cupli mounts detach <name>` | remove the bind. |
| `cupli mounts bridge [names]` | create/repair `host_bridge` symlinks. |
| `cupli mounts unbridge [names]` | remove cupli-created `host_bridge` symlinks. |

### Exports

| Command | What |
|---|---|
| `cupli exports list` | every declared export and its status (`missing`/`stale`/`seeded`/`synced`). |
| `cupli exports sync [names]` | materialise / refresh host copies. |
| `cupli exports clean [names]` | remove `sync` host copies (`bind-seeded` data kept). |

### Hooks

| Command | What |
|---|---|
| `cupli hooks install <hooks-dir> [--scope all/apps/bases/mounts] [--target name]` | install per-target git-hook shims. |
| `cupli hooks remove [--scope] [--target]` | remove shims. |

Hook scripts under `<hooks-dir>/<hook-name>/*.sh` are dispatched into the
target's container. A first-line directive overrides the defaults:

```bash
#!/usr/bin/env bash
# cupli: container=api workdir=/app shell=sh
echo "running inside the container"
```

`shell=sh` switches the in-container interpreter from `bash` (default) to
POSIX `sh` — useful for alpine-based images that have no `bash`.

### IDE

| Command | What |
|---|---|
| `cupli ide setup [--target auto/vscode/pycharm/all] [--force]` | write JSON-schema mappings for the workspace. `auto` walks up looking for `.vscode/` / `.idea/` (stops at the git-repo boundary) and writes only for the editor(s) found. |

### Diagnostics

| Command | What |
|---|---|
| `cupli graph` | tree of bases / apps / mounts / commands. |
| `cupli dashboard [-i interval]` | live status table. |
| `cupli stats [--follow]` | `docker stats` scoped to the workspace. |
| `cupli explain <code>` | error code reference. |

---

## Recipes

### Single inline service, no compose file

```yaml
schema_version: 1
name: hello
apps:
  cache:
    service:
      image: redis:7-alpine
      command: ["redis-server", "--appendonly", "yes"]
    ports: ["6379:6379"]
```

### Compound app (celery)

```yaml
apps:
  backend:
    vars: {DATABASE_URL: ..., REDIS_URL: ...}
    services:
      backend:
        image: ${IMAGE}
        command: [uvicorn, app.main:app]
        ports: ["8000:8000"]
      celery-worker:
        image: ${IMAGE}
        command: [celery, -A, app.tasks, worker]
        depends_on: [backend]
      celery-beat:
        image: ${IMAGE}
        command: [celery, -A, app.tasks, beat]
        depends_on: [backend]
```

Full file: [`docs/examples/celery/`](docs/examples/celery/).

### Multi-repo workspace

* `repo:` + `branch:` on every app/mount that has its own checkout.
* `cupli init` clones them under `src/apps/<name>`.
* `cupli git status` aggregates state across all of them.

Full file: [`docs/examples/multi-repo-shop/`](docs/examples/multi-repo-shop/).

### Renaming a compose service

```yaml
apps:
  redis:
    service: cache-redis             # compose-fragment calls it cache-redis
    composes: [./compose.yml]
```

### Hot-swap a vendored SDK

```yaml
mounts:
  shared-sdk:
    repo: git@github.com:example/shared-sdk.git
    hosted_in: [shop-web]
    exec_path: /opt/shared-sdk
```

```bash
cupli mounts attach shared-sdk        # mount in
cupli mounts detach shared-sdk        # mount out
```

### Per-repo branch on checkout

```bash
cupli git checkout main                                 # all repos → main
cupli git checkout main -t shop-api -t shop-web         # only these two
cupli git checkout -m shop-api=feature/x -m shop-web=main
```

### Tag-based filtering

```yaml
apps:
  postgres: {tags: [infra, db]}
  redis:    {tags: [infra, cache]}
  shop-api: {tags: [backend]}
```

```bash
cupli up --tag infra            # only postgres + redis
```

### Targeting one service of a compound app

```bash
cupli up backend                # all services owned by `backend`
cupli up celery-worker          # only that compose-service of the compound app
cupli up celery-worker celery-beat   # several specific services
```

### Custom networks

```yaml
networks:
  shared-net:
    name: my-org-shared
    driver: bridge
  monitoring:
    driver: bridge

apps:
  api:
    service:
      image: ...
      networks: [default, shared-net]   # `default` is cupli's auto network
  metrics:
    service:
      image: ...
      networks: [monitoring]
```

### Named volumes, secrets, configs

Top-level `volumes:` / `secrets:` / `configs:` are merged verbatim into
`docker-compose.pre.yml`, so an inline service can reference them without a
separate compose file. No synthetic `default` is injected (unlike `networks`),
and an empty block is omitted from the output.

```yaml
volumes:
  minio_data:            # null body == default-driver named volume

secrets:
  ci_token:
    environment: CI_JOB_TOKEN

apps:
  minio:
    service:
      image: minio/minio
      command: server /data
      volumes: [minio_data:/data]   # references the named volume above
```

---

## IDE setup

`cupli init` and `cupli ide setup` write JSON-schema mappings for the
editor(s) it detects around the workspace (`auto` walks parent dirs up
to the git-repo boundary, looking for `.vscode/` or `.idea/`). Every
generated `space.cupli.yaml` also carries a
`# yaml-language-server: $schema=...` directive on line 1, so modern
editors pick the schema up even without the config files.

### VS Code

Install the [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml).
That's it — the schema directive is honoured. Optional pinning if you
prefer:

```json
// .vscode/settings.json
{
  "yaml.schemas": {
    "./space.schema.json": "space.cupli.yaml"
  }
}
```

### PyCharm / IntelliJ

The bundled YAML plugin understands `# yaml-language-server: $schema=`
directives in IntelliJ 2023.2+. If yours doesn't:

`Settings → Languages & Frameworks → Schemas and DTDs → JSON Schema
Mappings → +`

* Name: `cupli space`
* Schema file: pick `space.schema.json` from the repo root
* File path pattern: `space.cupli.yaml` (or `*.cupli.yaml`)

### neovim with LSP

`yaml-language-server` understands the inline directive. Make sure it's
running on `*.cupli.yaml`.

### Generating the schema

The schema lives at [`space.schema.json`](space.schema.json) and is
generated from the Pydantic models:

```bash
make schema       # or: uv run python scripts/generate_schema.py
```

Re-run after changing `src/cupli/domain/models.py`.

> **Why JSON Schema for a YAML file?** JSON Schema is the editor-side
> contract — both `yaml-language-server` (VS Code, neovim) and
> IntelliJ's bundled YAML support understand it natively and apply it
> to YAML files. No conversion needed.

### Custom file icon for `space.cupli.yaml`

JSON-Schema mappings don't change file icons. If you want the cupli
logo on the file in your project tree:

**VS Code (with [Material Icon Theme](https://marketplace.visualstudio.com/items?itemName=PKief.material-icon-theme))**
— add to `.vscode/settings.json`:

```json
{
  "material-icon-theme.files.associations": {
    "space.cupli.yaml": "docs/resources/logo.svg",
    "*.cupli.yaml": "docs/resources/logo.svg"
  }
}
```

**PyCharm / IntelliJ** — a custom file icon needs a real Kotlin plugin
(`FileIconProvider` extension point); JSON-Schema mappings alone can't
do it.

---

## Limitations

* **One project at a time.** A `space.cupli.yaml` maps to exactly one
  docker-compose project. To compose two cupli workspaces, share infra
  via external networks.
* **No native Kubernetes.** Compose-only.
* **No remote build farm.** Builds run locally via `docker compose`.
* **No secrets management.** Use `.env.local` (gitignored) and the
  usual `${VAR}` substitution. Cupli doesn't ship a vault integration.
* **Schema v1.** Forward-incompatible breaking changes are gated on
  `schema_version`. `cupli upgrade-config` is the migration path
  placeholder.

---

## Troubleshooting + error codes

`cupli explain <code>` prints the full description. The cheat-sheet:

| Code | Meaning |
|---|---|
| `E001` | Space file not found. |
| `E002` | Validation failed (pydantic). Per-field messages include `file:line:col`. |
| `E003` | Empty / comment-only space file. |
| `E004` | YAML syntax error. |
| `E014` | Variable interpolation cycle. |
| `E015` | User variable shadows a reserved auto-var. |
| `E016` | Unknown `${VAR}` reference under `--strict-vars`. |
| `E017` | `git clone` failed. |
| `E020` | Unknown name (app / mount / target / space). |
| `E028` | Unknown cupli error code (catch-all). |
| `E029` | Space file already exists. |
| `E030` | Per-component env-var name collision (e.g. `shop-api` and `shop_api` both → `SHOP_API_APP_PATH`). |

For `cupli space doctor` and `cupli config` errors, the output now
includes a per-field summary with source locations.
