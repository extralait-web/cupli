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
