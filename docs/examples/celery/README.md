# examples/celery

A backend app driving several compose-services (web + N celery workers + beat)
from one place. Shows the `services:` MAP form of compound apps.

## What it shows

* **`services:` map** — one cupli app drives multiple docker-compose services.
  Each key under `services:` is a compose service name; each value is an
  ordinary docker-compose service spec plus optional `vars` / `ports`.
* **Shared base** — `image`, env, and `depends_on` written once, applied
  to every worker.
* **Per-service override** — `celery-worker-default` and
  `celery-worker-heavy` only differ in `command:` and a per-service
  `vars.CELERY_LOG_LEVEL`.
* **Default ports + opt-out** — app-level `ports: ["8000:8000"]` flows
  into the primary service automatically; workers opt out with
  `ports: []`.
* **Cross-app `deps:`** — backend waits on `postgres` and `redis` to
  start. Cupli writes the compose `depends_on` entry.

## Inline compose attributes

Both `service:` and `services:` accept **any** docker-compose attribute
verbatim:

```yaml
service:
  image: ...
  build: {...}
  command: [...]
  environment: {...}
  healthcheck: {...}
  depends_on: [...]
  volumes: [...]
  restart: ...
  # ... anything else docker-compose understands
```

Cupli-specific keys (`vars`, `ports`) are siblings of the compose
attributes; they get cupli-style treatment (merge / replace).

## Try it

```bash
cupli -f space.cupli.yaml up
cupli -f space.cupli.yaml ps
cupli -f space.cupli.yaml logs celery-worker-default -f
cupli -f space.cupli.yaml exec -c celery-worker-default -- \
    celery -A app.tasks inspect active
cupli -f space.cupli.yaml stop celery-worker-heavy   # stop one worker
cupli -f space.cupli.yaml down
```

## Filtering with `--tag`

The `tags: [infra]` on `redis` and `postgres` lets you start infra
only:

```bash
cupli up --tag infra
```
