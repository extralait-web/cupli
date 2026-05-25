# examples/multi-repo-shop

A realistic multi-repository workspace: separate git repos for backend,
frontend, and a shared SDK, plus infra services (postgres + redis)
declared inline.

## What it shows

* **Multi-repo orchestration** — each app/mount with `repo:` is cloned
  on `cupli space sync` and watched by `cupli git status`.
* **`branch:` pinning** — every repo-backed component pins `main`;
  `cupli git status` flags drift when working trees move.
* **Mixed declaration styles**:
  * `service:` *dict* for inline-only infra (`postgres`, `redis`).
  * `composes:` *file* for apps with their own Dockerfile + compose
    fragment (`shop-api`, `shop-web`, `migrate`).
* **Bases** with `composes:` and `vars:` — DRY between python/node apps.
* **Mounts** — `shared-sdk` bind-mounts on demand via
  `cupli mounts attach/detach`.
* **Workspace commands** — `cupli lint` / `cupli test` are promoted to
  top-level; `cupli sc shell-pg` / `cupli sc alembic-revision` reachable
  via shortcut.

## Layout cupli expects

```
multi-repo-shop/
├── space.cupli.yaml
├── .env.example                   # copy to .env, edit if needed
├── infra/                         # purely-infra compose files (if any)
└── src/                           # cupli's default checkout root
    ├── apps/{shop-api, shop-web}  # cloned by `cupli space sync`
    ├── bases/{python_runtime, node_runtime}
    └── mounts/shared-sdk
```

`src/apps/`, `src/bases/`, `src/mounts/` are the **defaults** — see
`APPS_PATH` / `BASES_PATH` / `MOUNTS_PATH` auto-vars. You can override
any of them with an explicit `path:` on the component.

## Quick-start

```bash
cd examples/multi-repo-shop
cp .env.example .env                                 # if you have one
cupli init                                            # registers + clones every declared repo
cupli up                                              # builds + starts everything
cupli ps
cupli logs shop-api -f
cupli sc lint                                         # also `cupli lint`
cupli mounts attach shared-sdk                        # bind shared SDK into shop-web
cupli git status                                      # status across every cloned repo
cupli git checkout main                               # switch every repo to main
cupli git checkout -m shop-api=feature/x              # per-repo branch
cupli down
```

## Tag-based filtering

```bash
cupli up --tag infra          # only postgres + redis
cupli stop --tag backend      # stop shop-api + migrate
```

## How it all fits together

* `vars.DATABASE_URL` lives on the `pg_client` base — every app that
  inherits `pg_client` gets it automatically.
* `apps.shop-api.bases: [python_runtime, pg_client, redis_client]`
  pulls in the python-runtime compose fragment AND inherits both DB /
  Redis URLs.
* `apps.shop-api.deps.migrate: [default]` makes `cupli up shop-api`
  also run the one-shot `migrate` service first.
* `mounts.shared-sdk.hosted_in: [shop-web]` lets
  `cupli mounts attach shared-sdk` bind-mount `src/mounts/shared-sdk/`
  into the web container at `/opt/shared-sdk`.

## Note

This example **references** repos like `git@github.com:example/...` that
don't actually exist. Replace them with your own URLs to make
`cupli init` / `cupli space sync` succeed. The shape of the YAML is the
point.
