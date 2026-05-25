# cupli examples

Four reference workspaces, smallest to largest. Every example has its
own README explaining what's new compared to the previous one.

| Example | Lines of YAML | Repos | Compose files | Demonstrates |
|---|---:|---:|---:|---|
| [`minimal/`](minimal/)          | ~25  | 0 | 0 | One inline service. `service:` as a dict. |
| [`celery/`](celery/)            | ~85  | 0 | 0 | Compound app via `services:` map. Workers + beat sharing one image. |
| [`multi-repo-shop/`](multi-repo-shop/) | ~140 | 3 | 4 | Realistic multi-repo workspace (backend + frontend + shared SDK). |
| [`full-reference/`](full-reference/) | ~280 | many | many | Every feature in one file, inline-commented. |

## How to use them

Each directory has its own `space.cupli.yaml`. `cd` into the example and
run cupli with `-f space.cupli.yaml`, OR register it once and then
operate by name:

```bash
cd examples/minimal
cupli workspace add -n minimal -f space.cupli.yaml
cupli -s minimal up
cupli -s minimal logs cache -f
cupli -s minimal down
```

For `multi-repo-shop`, the example YAML references real-looking but
imaginary URLs (`git@github.com:example/...`). Swap them for your own
repos before running `cupli init`.

## Inline `service:` / `services:` accept any docker-compose attribute

This is the most-asked question, so here's the cheat-sheet:

```yaml
apps:
  some-app:
    service:                  # OR `services: { name: {...}, name2: {...} }` OR `services: [name1, name2]`
      image: ...
      build: ...
      command: [...]
      environment: {...}
      volumes: [...]
      depends_on: [...]
      healthcheck: {...}
      restart: ...
      ulimits: {...}
      # ...any other docker-compose service attribute
      vars:                   # cupli-specific: merged into `environment`
        LOG_LEVEL: info
      ports:                  # cupli-specific: REPLACES app-level ports
        - "8080:8080"
```

Cupli intercepts `vars` and `ports`; everything else is written to a
generated `docker-compose.inline.yml` and merged by docker-compose as if you'd
written it in a regular compose file.

For compound apps you can also use the list shorthand —
`services: [api, worker, beat]` is exactly `{api: {}, worker: {}, beat: {}}`.
Use it when every service in the compound app just inherits the app-level
`vars` / `ports` and its compose spec lives in an external compose-fragment
listed under `composes:`.

## Editor / IDE setup

Every `space.cupli.yaml` in this repo has a
`# yaml-language-server: $schema=...` directive on line 1. Any editor
that understands JSON Schema for YAML (VS Code with the YAML extension,
PyCharm/IntelliJ with the YAML plugin) will pick it up automatically —
you'll get key completion, value validation, and hover documentation
for every field.

For an explicit local config, run `cupli ide setup` from the workspace
root. It walks up looking for an existing `.vscode/` or `.idea/` (stops
at the git-repo boundary) and writes the matching schema-mapping files
for the editor(s) it detects. `cupli init` calls the same flow on a
fresh workspace.
