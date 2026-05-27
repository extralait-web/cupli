# v0.3.0

Feature release extending workspace command shortcuts (`commands:`).

## Features

* **Command grouping.** A `group:` label groups a command under a panel in
  `cupli --help` and in the `cupli sc` listing.
* **Multi-line `run`.** `run` accepts a single line, a YAML block scalar, or a
  list of lines (joined with newlines) and runs via `sh -c`. The legacy `$@`
  passthrough is appended only for a single-line snippet with no declared args.
* **Typed arguments.** A `commands.<name>.args` list declares typed parameters
  (`str`/`int`/`bool`, positional or `--option`, with `help`, `short` alias,
  `required`/`default`). For top-level promoted commands they become real typer
  parameters shown in `cupli <name> --help`; for `cupli sc` they are parsed
  with click. Values are substituted into `run` via `{{name}}` placeholders and
  shell-quoted. A bare list of names is shorthand for required positional
  string arguments.
* **Multi-container commands.** `container:` accepts one app or a list, and a
  new `execute:` field selects `sequential` (default, fail-fast), `continue`
  (run all, non-zero if any failed), or `parallel` (concurrent, output
  captured per container).

## Docs

* `AGENTS.md` actualized with the new command capabilities and the top-level
  `volumes:` / `secrets:` / `configs:` blocks; READMEs now point agents at it.

# v0.2.0

Feature release adding three top-level docker-compose blocks to the space
schema.

## Features

* **Top-level `volumes:`, `secrets:`, `configs:` blocks.** A space can now
  declare named volumes, secret definitions and config definitions at the top
  level alongside `networks:`. They are merged verbatim into
  `docker-compose.pre.yml`, so inline services (`apps.<x>.service` /
  `services`) can reference them without a separate compose file — e.g. a
  `minio_data:/data` named volume or a `CI_JOB_TOKEN` build secret. No
  synthetic `default` is injected and an empty block is omitted. A null body
  (`minio_data:`) is treated as a default-driver entry.

# v0.1.2

Hotfix release that fixes broken GitHub URLs scaffolded into user workspaces
and surfaced by the IDE-setup command. The earlier ``v0.1.1`` tag was the
intended hotfix but never reached PyPI, so the same payload ships under
``v0.1.2`` alongside this URL fix.

## Fixes

* **Scaffolded `space.cupli.yaml` and IDE-setup link to `master`.** The
  default branch of `extralait-web/cupli` is `master`, but the
  `yaml-language-server` `$schema=` URL, the README reference comment in
  the scaffolded space, and `SCHEMA_URL_DEFAULT` all pointed at
  `https://raw.githubusercontent.com/extralait-web/cupli/main/…`, which
  404s. All three references now use `/master/`.

## Tests

* Coverage raised above the smokeshow gate (80%) with new unit and CLI
  suites for ``utils/json``, ``utils/subprocess``, ``utils/git``,
  ``domain/runtime``, ``core/cache``, ``cli/diagnostics``,
  ``cli/lifecycle``, ``cli/git`` and ``cli/_completion``.

# v0.1.1

Hotfix release on top of v0.1.0 to make CI green on a fresh runner and on
the full ubuntu / macos / windows × py3.10–3.13 matrix.

## Fixes

* **`create_file` now creates parent directories.** The per-user spaces
  registry at `${XDG_CONFIG_HOME:-~/.config}/cupli/spaces.json` was being
  touched without ensuring `cupli/` existed first, which made
  `cupli ... graph`, `examples-validate`, and ~70 unit/CLI tests fail on
  any machine that had never had `~/.config/cupli/`.
* **Test suite no longer relies on `FORCE_COLOR=0`.** A top-level
  `conftest.py` now pops `FORCE_COLOR` and sets `NO_COLOR=1` before any
  cupli module is imported, so rich-formatted output does not inject ANSI
  escape sequences that break substring assertions on captured stdout.
* **Windows compatibility in path assertions.** Loader tests that match
  computed `*_PATH` vars with a literal forward-slash suffix now normalise
  through `Path(...).as_posix()` so they pass under `WindowsPath`.
* **`install_hooks` chmod check skipped on Windows.** Windows file
  systems do not model POSIX executable bits, so the
  `st_mode & 0o111` assertion is `@pytest.mark.skipif` on `win32`.
* **`_pid_alive` uses `OpenProcess` on Windows.** CPython routes
  `os.kill(pid, 0)` to `GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)`
  on Windows, which actively sends `Ctrl+C` to a process group instead
  of probing liveness — that interrupted the test session as soon as
  the lock module checked an unknown PID. The Windows path now opens
  the process with `PROCESS_QUERY_LIMITED_INFORMATION` and inspects
  the exit code via `GetExitCodeProcess`.
* **Registry prefix detection accepts both separators.** The longest-
  prefix matcher hard-coded `/` as the directory delimiter, so
  `detect_current_space` could not locate a registered space from a
  Windows `cwd` under it. Both `/` and `os.sep` are now treated as
  valid separators.

# v0.1.0

Initial release.

## Highlights

* **Schema** (`schema_version: 1`) — top-level `apps`, `bases`, `mounts`,
  `hooks`, `commands`, `networks`; per-app `mode` / `service` / `services` /
  `forward_ssh`; per-mount `hosted_in` / `exec_path` / `mac_volume`.
* **Two ways to declare compound apps.** `services:` accepts either a map of
  service-name → override or a bare list of names:

  ```yaml
  services:                # map form: per-service overrides
    api: {}
    worker:
      vars: {LOG_LEVEL: debug}

  services:                # list form: just the names
    - api
    - worker
    - beat
  ```
* **Top-level `networks:`** carries any docker-compose `networks.<name>.*`
  spec verbatim and is merged into `docker-compose.pre.yml` alongside the
  auto-attached `default` workspace network.
* **Pydantic v2** models with cross-references (`bases`, `deps`,
  `hosted_in`, `commands.container`) validated by a single
  `model_validator`. Bare `vars:` (YAML null) is coerced to `{}`.
* **Line-aware parser** (ruamel.yaml round-trip) feeds a `LineMarks` lookup
  table that backs friendly validation errors.
* **Numbered error catalog** (`E001`–`E031`) plus `cupli explain <code>`.
  `E031` fires when a planned service is not declared in any compose source —
  surfaces the missing app + service before `docker compose` would error out.
* **CLI surface** — `init`, `workspace add/list/select/unselect/remove`,
  `space sync/doctor`, `up/stop/restart/down/ps/logs/build/pull/compose/config/
  watch`, `exec/run/shell/wrap/sc`, `mounts list/attach/detach`,
  `hooks install/remove`, `git status/pull/fetch/checkout`, `ide setup`,
  `dashboard`, `env`, `explain`, `upgrade-config`, `completion`,
  `--list`/`--version`. `cupli up` accepts `--tag <t>` (repeatable),
  `--mode default|hook|full` and bare service names — including individual
  services of compound apps (`cupli up api-1` targets just that service).
* **Compose overrides** are emitted into the per-space state dir using
  docker-compose naming convention:
  `docker-compose.pre.yml` (defaults — network, container_name; merged
  BEFORE user composes), `docker-compose.post.yml` (forced — env injection,
  ports, mount volumes, cross-file `depends_on`; merged AFTER) and
  `docker-compose.inline.yml` for services declared inline under
  `apps.<x>.service` / `apps.<x>.services`. Deps on `mode: oneshot` apps
  emit `condition: service_completed_successfully` so dependants block on the
  one-off command.
* **Hooks-in-docker (elc-style)** — `cupli hooks install <dir>` installs
  idempotent bash shims tagged with `# cupli-hook v1`. Per-script first-line
  directives override defaults: `# cupli: container=node workdir=/app shell=sh`.
  `shell=` lets alpine-only images use busybox `sh`; default stays `bash`.
  Pre-commit-framework conflicts surface as `E024` unless `--force` is passed.
* **Workspace commands** declared under `commands:` are surfaced through
  `cupli sc <name>` (with optional `top_level: true` to expose as bare
  `cupli <name>`). `run:` is a shell command line — cupli wraps it in
  `sh -c` so `&&`, `|`, `${VAR}` work inside the container.
* **C3 linearisation** for `apps[*].bases` — deterministic even under
  diamond inheritance when nested bases land later.
* **Parallel `space sync`** via `concurrent.futures.ThreadPoolExecutor`.
  `${VAR}` references in `repo:` / `branch:` / `post_clone:` are substituted
  before invoking git, so self-hosted file:// URLs and parameterised branches
  work.
* **Scaffold** (`cupli init`) writes a minimal layout: `space.cupli.yaml`,
  `.env`, `.locals/`. `src/apps/`, `src/bases/`, `src/mounts/` are created
  lazily by `cupli space sync` when a declared component first needs them.
* **State directory** layout under `.locals/<space>/state/`:
  `docker-compose.pre.yml`, `docker-compose.post.yml`,
  `docker-compose.inline.yml`, `override.env`, `vars.json`, `cache.json`,
  `hooks-manifest.json`, `active-mounts.json`, `lock`.
* **IDE integration** — `cupli ide setup` walks up from the workspace
  looking for `.vscode/` / `.idea/` (stopping at the git-repo boundary) and
  writes JSON-schema mappings only for the editor(s) found. On a brand-new
  workspace where nothing is detected, writes both as a safe default.
  `cupli init` calls the same flow.
* **Layered architecture** enforced by an `.importlinter` config:
  `cli → services → core → domain → utils`.

<!-- package description limit -->
