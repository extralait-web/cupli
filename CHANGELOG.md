# v0.5.2

Patch release.

## Fixes

* **``cupli down <service>`` no longer silently tears the whole stack down.**
  ``down_command`` discarded the service-name half of the passthrough split,
  so ``cupli down kanchi`` ran a full ``docker compose down --remove-orphans``
  and removed every container in the workspace. ``down`` now declares an
  optional ``services`` positional: with services named, only those
  containers go down (``docker compose down [SERVICES…]`` — compose v2
  supports the per-service form); without arguments the workspace-wide
  teardown behaviour is unchanged. The other lifecycle verbs (``up``,
  ``stop``, ``restart``, ``ps``, ``logs``, ``build``, ``pull``) were audited
  at the same time and already forward service names correctly.

# v0.5.1

Patch release.

## Fixes

* **`cupli --list` works under typer ≥0.25 / click ≥8.4.** Newer typer
  restructured the class hierarchy so ``TyperGroup`` is no longer a subclass
  of ``click.Group``. The ``isinstance(cmd, click.Group)`` guard in
  ``_list_commands`` and the builtin-collision check silently returned an
  empty group, hiding every command from ``cupli --list``. The guard now
  duck-types ``obj.commands`` so cupli is compatible with both old and new
  typer/click lines. ``cupli --list`` and top-level shortcut promotion work
  under a fresh ``pipx install`` again.

# v0.5.0

Feature release: compose-style start conditions for `apps[*].deps`.

## Features

* **Compose start conditions on `deps`.** A dependency in
  ``apps[*].deps`` can now declare its docker-compose start condition
  (``service_started`` / ``service_healthy`` /
  ``service_completed_successfully``) plus the ``restart`` and ``required``
  flags. Previously cupli always rendered ``service_started`` (with a special
  case to ``service_completed_successfully`` for ``mode: oneshot`` deps),
  which forced workspaces to ship ``wait-for-pg`` scripts to actually wait for
  a healthy database. Now:

  ```yaml
  apps:
    core-back:
      deps:
        postgres: service_healthy       # condition shorthand
        redis: ~                         # default (service_started)
        migrate:                         # full DepSpec form
          condition: service_completed_successfully
          modes: [default]
          restart: true
          required: true
  ```

  Accepted ``deps`` value forms (back-compat preserved):

  - list of names → defaults (unchanged);
  - ``~`` (null) → defaults;
  - string → condition shorthand;
  - list of mode tags → ``modes`` for ``--mode`` filtering (unchanged);
  - mapping → full ``DepSpec`` (``modes`` / ``condition`` / ``restart`` /
    ``required``).

  Mode-tag and condition name spaces are disjoint, so a bare string is
  unambiguous. Cupli forwards ``restart`` / ``required`` to compose only when
  they differ from compose defaults.

# v0.4.2

Patch release.

## Fixes

* **File-placeholder for sub-binds is read-only on the host.** Cupli pre-creates
  a 0-byte file on the host for every sub-bind whose source is a single file
  (e.g. ``mkdocs.yml`` mounted at ``/app/mkdocs.yml``). The placeholder is just
  a mount point — docker overlays the bind source on top inside the container,
  and the host file stays empty by design. To stop IDEs and humans from editing
  that empty file by mistake, the placeholder is now created with ``chmod
  0o444``. Docker mount ignores host perms, so the running container is
  unaffected. Directory placeholders keep their default perms (some are
  parents to other sub-bind placeholders and need write perm during prep).

# v0.4.1

Patch release.

## Fixes

* **Pre-create host placeholders for sub-mounts under bind targets.** Docker
  daemon (running as root) creates a missing mount point on demand, so under a
  bind ``host:/app`` plus sub-mounts targeting ``/app/<sub>`` (named volumes,
  cupli mounts, additional binds) the daemon ended up creating those host
  placeholders as **root** — leaving root-owned junk on the host. Cupli now
  resolves the merged compose config before ``up`` / ``build`` / ``run`` /
  ``watch`` and pre-creates each placeholder as the current user; the daemon
  finds an existing mount point and skips the root creation. Idempotent and
  silent on every failure mode — prep never blocks compose.

# v0.4.0

Feature release: workspace-command ergonomics and variable interpolation.

## Features

* **Undeclared command args pass through (+ `strict`).** When a
  `commands.<name>` declares `args`, CLI tokens that don't match a declared arg
  (flags and positionals) are forwarded verbatim to the end of the command —
  e.g. `cupli sc deploy prod --force-recreate`. A new `strict: true` attribute
  restores reject-unknown.
* **`cupli sc <name>` are real, typed subcommands.** `sc` is now a group whose
  subcommands resolve live from the active space (`-f` / `-s` / cwd, cold cache,
  or freshly edited YAML); declared `args` parse, appear in `cupli sc <name>
  --help`, and tab-complete. Completion is per-space (no cross-space leakage).
* **Builtin compose verbs forward unknown flags.** `up` / `down` / `build` /
  `pull` / `stop` / `restart` / `ps` / `logs` pass unknown flags through to
  docker compose (e.g. `cupli up --force-recreate`); service names are not
  mistaken for flags. Use the `--opt=value` form for value-taking flags.
* **Bare `$VAR` interpolation.** `$VAR` is recognised alongside `${VAR}` and
  `${VAR:-default}`; `$$` escapes a literal `$` (docker-compose convention).
* **env-file values are interpolated against the cupli scope.** A value such as
  `DATABASE_URL=postgres://db:${POSTGRES_PORT}/app` inside an env file now
  resolves `${POSTGRES_PORT}` from `vars` / earlier env layers, so
  port-dependent wiring and credential reuse can live in env files, not only in
  `vars:`.
* **Richer schema completion.** `service:` / `services:` compose-service fields
  in the JSON schema were expanded to the compose-spec set (~88 properties:
  `cpus`, `mem_limit`, `network_mode`, `sysctls`, `gpus`, `extends`, `develop`,
  …) for accurate editor completion and hover docs.

## Fixes

* A declared `envs:` file is read with interpolation disabled, so python-dotenv
  no longer collapses cupli-scope `${VAR}` references to empty strings.
* A missing declared `envs:` file warns under `--strict-vars` (silent by
  default to preserve optional `.env.local`).

# v0.3.1

Hotfix release.

## Fixes

* **`click` is now a declared dependency.** `v0.3.0` imports `click` directly
  (for the typed command-shortcut parameters), but relied on it being present
  transitively via `typer`. In environments where `typer` does not pull `click`
  in (e.g. a `pipx install`), `cupli` crashed on startup with
  `ModuleNotFoundError: No module named 'click'`. `click` is now listed in the
  project dependencies so it is always installed.

## Chores

* **Bumped GitHub Actions off the deprecated Node 20 runtime.** `actions/checkout`
  → v6, `actions/setup-python` → v6, `actions/upload-artifact` → v7,
  `actions/download-artifact` → v8, `astral-sh/setup-uv` → v7,
  `dawidd6/action-download-artifact` → v21.

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
