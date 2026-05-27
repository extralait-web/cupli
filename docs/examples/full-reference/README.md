# examples/full-reference

Every cupli feature in one file, with inline comments on every option.

This is the same file as the repo-root `space.cupli.yaml`; kept here so
the `examples/` directory contains a complete catalogue.

## What's in it

| Feature | Where to look |
|---|---|
| Schema version + name + tool guards | top of file |
| `extends:` parent space | commented line after `cupli_max` |
| `envs:` and `vars:` at space scope | top section |
| `bases:` with `composes`, `vars`, `envs`, `repo`/`branch`/`post_clone` | first bases block |
| App with **`service: "name"`** (string) — bind to existing compose service by name | `redis` app |
| App with **`service: {...}`** (dict) — inline single-service spec | `cache` app |
| App with **`services: {map}`** — compound app (api + workers + beat) | `api` app |
| App with **`services: [list]`** — list shorthand for empty per-service overrides | not in this file; see `examples/README.md` |
| App that defaults service name to itself (no `service:`) | `postgres` |
| Multi-base inheritance with C3 ordering | `api.bases: [python_runtime, pg_client]` |
| Cross-app `deps:` with mode filters | `api.deps`, `migrate.deps` |
| `ports:` injection | every infra app |
| Native compose `develop.watch` for `cupli watch` | `api.services.api.develop.watch` |
| `mode: oneshot` (run-once) | `migrate` |
| `forward_ssh: true` for SSH-agent forwarding | `api.forward_ssh` |
| `tags: [...]` for `--tag` filtering | every app |
| `mounts:` with `hosted_in`, `exec_path`, `mode`, `mac_volume` | `sdk` |
| `hooks:` per-target overrides | bottom |
| `commands:` shortcuts with `top_level:` | `lint`, `test`, … |
| Command `group:` (help panel) + multi-line `run:` | `db-reset` |
| Command typed `args:` (positional, `--option`, bool flag, `int`) | `db-migrate` |
| Command `args:` shorthand (bare list of names) | `tail-log` |
| Multi-container command with `execute:` (sequential/continue/parallel) | `pip-freeze` |
| Top-level `networks:` block | between `mounts:` and `hooks:` |
| Top-level `volumes:` / `secrets:` / `configs:` blocks | after `networks:` (`minio_data`, `ci_token`, `app_config`) |
| `${VAR}` interpolation, `${VAR:-default}` defaults | throughout |
| Per-component path-vars (`<NAME>_APP_PATH`, …) | `${API_APP_PATH}` inside `api.services.api.build.context` |

## Try it

```bash
cupli -f space.cupli.yaml graph        # tree of bases / apps / mounts / commands
cupli -f space.cupli.yaml env          # full resolved env
cupli -f space.cupli.yaml --list       # every CLI command grouped by area
```

`cupli up`/`cupli space sync` need real repos to exist — most of the
URLs here are placeholders, so use this file as documentation, not as
something you'd start.
