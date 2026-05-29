<p align="center">
  <img src="docs/resources/brand.svg" width="100%" alt="cupli">
</p>
<p align="center">
    <em>Оркестратор multi-repository docker-compose окружений. Один YAML, одна команда <code>cupli up</code> — весь стек поднят.</em>
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

> 🇬🇧 [README in English](README.md)

`cupli` нужен, когда каждый компонент проекта (backend, frontend,
worker, общий SDK, инфра) живёт в **отдельном git-репозитории**, но
весь стек надо одним движением поднять локально. Cupli — обёртка над
`docker compose`, не его замена.

* **Спека-first.** Один `space.cupli.yaml` описывает всё: репозитории,
  bases, mounts, services, ярлыки.
* **Inline или внешний compose.** Декларируй сервисы прямо в YAML или
  ссылайся на готовый `docker-compose.yml`. Можно совмещать.
* **Multi-repo git.** `cupli git status / pull / fetch / checkout`
  параллельно работают по всем клонированным компонентам, с фильтрами
  по именам и per-repo map для branches.
* **Scope переменных.** Space → bases (C3) → app, c `${VAR}` и
  `${VAR:-default}` подстановкой везде.
* **Pin веток + drift.** `branch: main` на компоненте уважается при
  `cupli init` (`git clone -b`) и подсвечивается в `cupli git status`,
  если working tree уехал в другую ветку.
* **Toggle mounts.** `cupli mounts attach <name>` бинд-маунтит общий
  SDK в N контейнеров без правки YAML.
* **Shell completion** для всех имён (apps, services, mounts, tags,
  shortcuts, коды ошибок).

> 🤖 **Редактируешь `space.cupli.yaml` через AI-агента?** Дай ему
> [`AGENTS.md`](AGENTS.md) — самодостаточный гайд по схеме, привязке сервисов,
> `commands:`, top-level блокам и кодам ошибок.

---

## Содержание

1. [Установка](#установка)
2. [Quick-start](#quick-start)
3. [Концепции](#концепции)
4. [Reference `space.cupli.yaml`](#reference-spacecupliyaml)
5. [CLI](#cli)
6. [Рецепты](#рецепты)
7. [Настройка IDE](#настройка-ide)
8. [Ограничения](#ограничения)
9. [Troubleshooting + коды ошибок](#troubleshooting--коды-ошибок)

---

## Установка

```bash
uv tool install cupli                 # рекомендую
# или
pipx install cupli
# или
pip install --user cupli
```

Проверка:

```bash
cupli -V                              # cupli 0.1.0 (удобно для скриптов)
cupli --version                        # полная инфа: python, platform, deps
```

Требуется Python ≥ 3.10. `docker` / `docker compose` должны быть в PATH.

### Shell completion

Авто-определение шелла из `$SHELL`:

```bash
cupli completion install
```

Или явно:

```bash
cupli completion install --shell bash      # bash | zsh | fish | pwsh
cupli completion show --shell zsh > ~/.zsh/completions/_cupli
```

---

## Quick-start

```bash
mkdir my-workspace && cd my-workspace
cupli init --name my-workspace                # каркас space.cupli.yaml + .env + .locals/
$EDITOR space.cupli.yaml                       # опиши свои apps
cupli up                                       # build + старт
cupli ps                                       # что запущено
cupli logs my-api -f
cupli down                                     # снести
```

Минимальный workspace:

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

Тот же workspace с комментариями: [`docs/examples/minimal/`](docs/examples/minimal/).

---

## Концепции

### Space

**Space** — единица, с которой работает cupli: один
`space.cupli.yaml`, один проект, один docker-compose project. У space
есть `name:` — он же имя docker-compose project'а и имя сети по
умолчанию.

### App

**App** — то, что cupli стартует/стопит. Каждый app биндится к одному
или нескольким compose-сервисам. Связывание объявляется одной из
четырёх форм:

1. Неявно — имя сервиса = имя app'а.
2. `service: "name"` — биндинг к существующему compose-сервису по имени.
3. `service: {image: ..., command: ..., ...}` — *inline*
   single-service spec, без отдельного compose-файла.
4. `services: { name1: {...}, name2: {...} }` — compound app с
   несколькими compose-сервисами (например: api + celery workers + beat).

В формах 3 и 4 dict принимает **любые** docker-compose-атрибуты
сервиса (`image`, `build`, `command`, `environment`, `depends_on`,
`healthcheck`, `volumes`, `restart`, …). Cupli резервирует `vars` и
`ports` для своих инъекций; всё остальное передаётся docker-compose
дословно через сгенерированный `docker-compose.inline.yml`.

### Base

**Base** — переиспользуемый шаблон. App'ы цитируют bases через
`bases: [name1, name2]` и наследуют `vars:`, `envs:`, `composes:`,
`repo:` в C3 порядке линеаризации. Bases убирают boilerplate.

### Mount

**Mount** — host-to-container bind, который можно включать/выключать
без правки YAML. Полезно для hot-swap общего SDK на локальный чекаут.
`cupli mounts attach/detach <name>` переключает состояние.

### Резолв на хосте для IDE (`host_bridge` и `exports`)

IDE индексируют **хостовую** ФС, тогда как cupli гоняет всё в контейнерах.
Две opt-in возможности закрывают разрыв (обе выключены по умолчанию и нужны
только для резолва в редакторе — не для запуска host-тулинга):

* **`host_bridge`** на mount держит инверсный host-симлинк
  (`<host-эквивалент exec_path> → mount.path`), чтобы либа, примонтированная
  под workdir приложения, была видна на хосте по тому же относительному пути,
  что и в контейнере. Управляется lifecycle (`up` / `mounts attach`/`detach`)
  или явно через `cupli mounts bridge` / `unbridge`.
* **`exports`** копирует container-built директорию (обычно named volume вроде
  `node_modules`) на хост. `strategy: sync` (default) зеркалит том по событиям
  `refresh_on`; `strategy: bind-seeded` превращает путь в живой host-bind.
  Управление: `cupli exports sync` / `clean`.

Они работают в связке: относительные симлинки внутри экспортированного
`node_modules` (`@scope/<lib> → ../../packages/<lib>`) резолвятся на хосте
только когда `packages/<lib>` тоже сбриджен. Есть асимметрия стеков — JS
remote-интерпретатор (Docker) **не** резолвит зависимости, поэтому
`node_modules` обязан быть на хосте; Python remote-интерпретатор резолвит
нормально, так что экспортировать `.venv` не стоит (экспорт `.venv`
пропускается без `rewrite_paths: true`). См. справку
[`exports.<name>`](#exportsname).

### Service

**Service** в cupli — это то же, что docker-compose называет service:
декларация контейнера. App владеет сервисами; один app может владеть
несколькими.

### Реестр workspace'ов

Spaces регистрируются в `~/.config/cupli/spaces.json`, можно
обращаться по имени откуда угодно:

```bash
cupli workspace add -n shop -f ~/work/shop/space.cupli.yaml
cupli -s shop up
cupli workspace select shop                 # sticky: следующие вызовы → shop
cupli workspace unselect                    # вернуть cwd-detect
```

---

## Reference `space.cupli.yaml`

Полный референс лежит в [`space.cupli.yaml`](space.cupli.yaml) в корне
и копией в [`docs/examples/full-reference/`](docs/examples/full-reference/).
Ниже — схема с однострочниками.

### Top-level

| Ключ | Тип | Default | Что делает |
|---|---|---|---|
| `schema_version` | int | — | Pin версии. Поддерживается только `1`. |
| `name` | string | — | Идентификатор. Используется как имя docker-compose project'а и имя сети по умолчанию. Регекс: `^[A-Za-z][A-Za-z0-9_-]*$`. |
| `cupli_min` / `cupli_max` | string \| `"*"` | — | Версии cupli. |
| `extends` | string | — | Путь к родительскому space (один уровень в v1). |
| `envs` | list[string] | `[]` | `.env`-файлы space-scope, до `vars`. |
| `vars` | map[str, str] | `{}` | Space-scope переменные; видны везде; пишутся в `override.env` для docker-compose substitution. |
| `bases` | map[str, base] | `{}` | Переиспользуемые шаблоны. |
| `apps` | map[str, app] | `{}` | Run units. |
| `mounts` | map[str, mount] | `{}` | Toggleable bind-mounts. |
| `hooks` | map[str, hook-override] | `{}` | Per-target тюнинг для `cupli hooks install`. |
| `commands` | map[str, command-shortcut] | `{}` | `cupli sc <name>` / `cupli <name>` (с `top_level: true`). |
| `networks` | map[str, dict] | `{}` | Top-level docker-compose `networks:`. Значения — compose-spec дословно (`driver`, `name`, `ipam`, …). Дефолтная сеть `default` добавляется автоматически. |
| `volumes` | map[str, dict] | `{}` | Top-level docker-compose `volumes:`. Именованные тома (compose-spec дословно), чтобы inline-сервисы ссылались на них без отдельного compose-файла. Пустое тело (`minio_data:`) — том с драйвером по умолчанию. |
| `secrets` | map[str, dict] | `{}` | Top-level docker-compose `secrets:`. Определения секретов (compose-spec дословно), на которые ссылаются `secrets:` уровня сервиса. |
| `configs` | map[str, dict] | `{}` | Top-level docker-compose `configs:`. Определения конфигов (compose-spec дословно), на которые ссылаются `configs:` уровня сервиса. |

### `bases.<name>`

| Ключ | Тип | Default | Что делает |
|---|---|---|---|
| `path` | string | `${BASES_PATH}/<name>` | Расположение на диске. |
| `repo` | string | — | Git URL (опустить — in-place base). |
| `branch` | string | — | Ветка для clone (`git clone -b <branch>`). |
| `post_clone` | string | — | Shell-команда после успешного clone. |
| `init_vars` | map | `{}` | Env, экспортированный в clone + `post_clone`. |
| `vars` | map | `{}` | Переменные, передающиеся в inheriting apps. |
| `envs` | list[string] | `[]` | Env-файлы base-scope. |
| `composes` | list[string] | `[]` | Compose-фрагменты, prepend'ятся в COMPOSE_FILE цепочку inheriting app'ов. |

### `apps.<name>`

| Ключ | Тип | Default | Что делает |
|---|---|---|---|
| `path` | string | `${APPS_PATH}/<name>` | Расположение на диске. |
| `repo` | string | — | Git URL. |
| `branch` | string | — | Ветка для clone. `cupli git status` подсвечивает drift. |
| `post_clone` | string | — | Shell-команда после clone. |
| `init_vars` | map | `{}` | Env для clone + `post_clone`. |
| `bases` | list[string] | `[]` | Bases (C3 multi-inherit). |
| `deps` | list[str] \| map[str, …] | `{}` | Кросс-app `depends_on`. List `[a, b]` или map с per-dep настройками (mode tags для `--mode`, compose condition / restart / required). См. [Условия зависимостей](#условия-зависимостей). |
| `tags` | list[string] | `[]` | Для `cupli up --tag <tag>`. |
| `mode` | enum | `up` | `up` (long-running), `oneshot` (run-once), `disabled`. |
| `composes` | list[string] | `[]` | Внешние compose-файлы. |
| `service` | string \| dict | — | Single-service binding. Dict-форма = inline compose-spec. |
| `services` | map[str, dict] \| list[str] | — | Multi-service map (каждое значение — compose-spec с опциональными cupli-only `vars` и `ports`) либо просто список имён сервисов (эквивалентно map с пустыми override). Несовместимо с `service`. |
| `vars` | map | `{}` | Переменные; инжектятся как `environment` на каждый managed сервис. |
| `envs` | list[string] | `[]` | Env-файлы app-scope. |
| `ports` | list[string] | `[]` | Compose-style port mappings; инжектятся в primary-сервис app'а (или в каждый сервис в `services:`). |
| `forward_ssh` | bool | `false` | Mount `$SSH_AUTH_SOCK` в контейнер. |

#### Все 4 формы service-binding'а

```yaml
# 1) Неявная (имя сервиса = имени app'а)
apps:
  api: {}

# 2) Строка (rename binding)
apps:
  redis:
    service: agora-redis        # bind к compose-сервису `agora-redis`
    composes: [./compose.yml]

# 3) Inline single-service (любые docker-compose атрибуты)
apps:
  cache:
    service:
      image: memcached:1.6
      command: ["memcached", "-m", "64"]
      healthcheck: {test: ["CMD", "echo", "stats", "|", "nc", "localhost", "11211"]}
    vars: {LOG_LEVEL: info}
    ports: ["11211:11211"]

# 4) services map (один app, N compose-сервисов)
apps:
  backend:
    vars: {DATABASE_URL: ...}   # шарится со всеми сервисами ниже
    services:
      backend:
        image: ${IMAGE}
        command: [uvicorn, app.main:app]
      celery-worker:
        image: ${IMAGE}
        command: [celery, -A, app.tasks, worker]
        vars: {CELERY_LOG_LEVEL: info}    # per-service override (merge)
        ports: []                          # explicit empty: opt out app-level ports

# 4b) services как список — то же самое, что `{name: {}}` для каждого
apps:
  fleet:
    composes: [${APP_PATH}/docker-compose.yml]
    services:
      - api
      - worker
      - beat
```

> `${VAR}` внутри inline compose-spec (`service.build.context: ${APP_PATH}`)
> резолвит **docker-compose**, не cupli. Для пути конкретного компонента
> используй `${<APP_NAME>_APP_PATH}` (per-component path-var, который cupli
> пишет в `override.env`). Голое `${APP_PATH}` подставляется только там, где
> подстановку делает сам cupli (например `composes:`).

### `mounts.<name>`

| Ключ | Тип | Default | Что делает |
|---|---|---|---|
| `path` | string | `${MOUNTS_PATH}/<name>` | Host-source dir. |
| `repo` | string | — | Git URL. |
| `branch` | string | — | Ветка для clone. |
| `post_clone` | string | — | After-clone host-команда. |
| `hosted_in` | list[string] | required | App-имена, в каждый сервис которых попадёт bind. |
| `exec_path` | string | required | Абсолютный POSIX-путь внутри контейнера. |
| `mode` | enum | `rw` | `rw` \| `ro`. |
| `mac_volume` | enum | — | macOS volume consistency hint. |
| `host_bridge` | bool \| map | `false` | Держать инверсный host-симлинк, чтобы host-тулинг (IDE) видел mount по container-относительному пути. `true` авто-выводит линк из workdir-bind хостящего приложения; map (`{link, relative}`) переопределяет. См. [host_bridge и exports](#резолв-на-хосте-для-ide-host_bridge-и-exports). |
| `envs` | list[string] | `[]` | Env-файлы. |
| `vars` | map | `{}` | Переменные. |

### `exports.<name>`

Материализация директории, собранной внутри контейнера (обычно named volume
вроде `node_modules`), на хост — чтобы IDE, резолвящие только из локальной ФС,
её проиндексировали. **Для индексации в IDE, не для запуска host-тулинга** —
экспортированные нативные бинари могут быть собраны под libc образа, не хоста.

| Ключ | Тип | Default | Что делает |
|---|---|---|---|
| `from` | string | required | Приложение (одно), сервис которого владеет директорией-источником. |
| `exec_path` | string | required | Абсолютный POSIX-путь источника внутри контейнера. |
| `path` | string | required | Путь назначения на хосте (`${VAR}` резолвятся в scope). |
| `strategy` | enum | `sync` | `sync` (оставить named volume, копировать на хост по `refresh_on`) или `bind-seeded` (превратить `exec_path` в host-bind, засидив из образа — всегда live). |
| `refresh_on` | list[enum] \| string | `[build]` | Lifecycle-события для рематериализации: `up`, `build`, `restart`. |
| `gitignore` | bool | `true` | Добавить `path` в корневой `.gitignore` (в секцию `# cupli exports`). |
| `mac_volume` | enum | — | macOS volume consistency hint. |
| `rewrite_paths` | bool | `false` | Experimental: синкнуть `.venv`-подобный экспорт и переписать абсолютные container-пути (`/app/...`) в `.pth` / `.egg-link` на host-эквиваленты. Без флага `.venv`-подобный экспорт пропускается (`E034`). |

### `commands.<name>`

| Ключ | Тип | Default | Что делает |
|---|---|---|---|
| `container` | string \| list[string] | required | Имя app'а (или список), в primary-сервисе которого выполнится команда. Список — выполнить в каждом. |
| `run` | string \| list[string] | required | Shell command line. Block scalar или список строк склеиваются через `\n` и исполняются через `sh -c`. Плейсхолдеры `{{name}}` подставляются из `args`. |
| `workdir` | string | — | Рабочая директория внутри контейнера. |
| `help` | string | — | Help-строка в `cupli --help`. |
| `top_level` | bool | `false` | Если true, доступно как `cupli <name>` (помимо `cupli sc <name>`). |
| `group` | string | — | Метка; группирует команду в панель в `cupli --help` и в листинге `cupli sc`. |
| `execute` | enum | `sequential` | Для мульти-контейнерной команды: `sequential` (fail-fast), `continue` (выполнить все, ненулевой если хоть один упал), `parallel`. |
| `args` | list[arg] | `[]` | Типизированные параметры, видны в `cupli <cmd> --help` и подставляются в `run` через `{{name}}`. Голый список имён — сокращение для обязательных позиционных string-аргументов. |
| `strict` | bool | `false` | Если false — токены, не совпавшие с объявленным `arg` (флаги и позиционные), пробрасываются в конец команды; если true — неизвестные токены отвергаются. |

#### `commands.<name>.args[]`

| Ключ | Тип | Default | Что делает |
|---|---|---|---|
| `name` | string | required | Идентификатор; плейсхолдер `{{name}}` и имя CLI-аргумента/опции. |
| `help` | string | — | Описание в `cupli <cmd> --help`. |
| `type` | enum | `str` | `str`, `int` или `bool`. `bool` всегда опция (флаг). |
| `option` | bool | `false` | Если true — опция `--name`; иначе позиционный аргумент. |
| `short` | string | — | Однобуквенный алиас для опции (`l` → `-l`). |
| `required` | bool | `false` | Обязателен ли. Взаимоисключающе с `default`. |
| `default` | string | — | Значение, подставляемое при отсутствии. |

```yaml
commands:
  db-migrate:
    group: Database                 # `cupli --help` покажет в панели "Database"
    container: api
    run: python manage.py migrate {{app}} {{fake}}
    args:
      - name: app                   # обязательный позиционный: `cupli db-migrate users`
        required: true
        help: Django app label.
      - name: fake                  # bool -> флаг `--fake`
        type: bool
    top_level: true

  pip-freeze:
    container: [api, worker]        # запуск в нескольких сервисах
    execute: parallel               # sequential (деф) | continue | parallel
    run: pip freeze
```

Многострочный скрипт — block scalar (команды по строкам; для fail-fast добавь
`&&` или `set -e`):

```yaml
  setup:
    container: api
    run: |
      python manage.py migrate
      python manage.py loaddata initial
```

### Auto-vars (доступны для interpolation всегда)

* **Space scope** — `SPACE_NAME`, `SPACE_PATH`, `APPS_DIR`,
  `APPS_PATH`, `BASES_DIR`, `BASES_PATH`, `MOUNTS_DIR`, `MOUNTS_PATH`,
  `LOCALS_DIR`, `LOCALS_PATH`, `NETWORK`, `COMPOSE_PROJECT_NAME`.
* **Per-component** — `<NAME>_APP_PATH` для каждого app,
  `<NAME>_BASE_PATH` для каждого base, `<NAME>_MOUNT_PATH` для
  каждого mount, `<NAME>_EXPORT_PATH` для каждого export. Имя upper-case +
  `-` → `_`. Видно в YAML И в `override.env`. Mount с явным
  `host_bridge.link` также экспортит `<NAME>_BRIDGE_PATH`.
* **App / base** — `APP_NAME`, `APP_PATH`, `APP_LOCAL_PATH` (только apps).
* **Mount** — `MOUNT_NAME`, `MOUNT_PATH`, `MOUNT_HOST`, `MOUNT_EXEC_PATH`.
* **Export** — `EXPORT_NAME`, `EXPORT_PATH`, `EXPORT_EXEC_PATH`.

Дефолтные пути: `APPS_PATH` = `$SPACE_PATH/src/apps`, аналогично для
bases и mounts. Override per-component через явный `path:`.

### Правила interpolation

* `${VAR}`, `${VAR:-literal-default}` и bare `$VAR` распознаются. `$$` —
  экранирование литерального `$` (соглашение docker-compose).
* Вложенные `${...}` внутри default'а НЕ поддерживаются — default literal.
* Циклы → `E014`.
* Unknown vars → `""` + жёлтый warning. С `--strict-vars` → hard error (`E016`).
* Shadow reserved auto-var → `E015`, если не передан `--allow-shadow`.

---

## CLI

`cupli --help` показывает всё. Основные:

### Lifecycle

| Команда | Что |
|---|---|
| `cupli up [services] [--tag t] [--mode m] [--build] [--pull p]` | `docker compose up`. В качестве `services` можно указывать как имя app'а, так и конкретные compose-сервисы compound app'а из `services:`. |
| `cupli stop [services] [--tag t]` | `docker compose stop`. |
| `cupli restart [services] [--tag t] [--hard]` | restart; `--hard` = down+up. |
| `cupli down [-v] [--images]` | `down --remove-orphans`; опционально volumes + images. |
| `cupli ps [--tag t]` | таблица сервисов. |
| `cupli logs [service] [-f]` | per-service или все. |
| `cupli build [services] [--tag t]` | build images. |
| `cupli pull [services] [--tag t]` | pull images. |
| `cupli compose -- <args>` | pass-through к `docker compose`. |
| `cupli config` | merged compose configuration. |
| `cupli watch [services]` | `docker compose watch` — для `develop.watch` сервисов. |

`--mode default|hook|full` фильтрует cross-app `deps:` по их mode-list.
Полезно для dev-vs-prod-style зависимостей: `api: {deps: {redis: [default, full]}}`
подтянет redis в обоих режимах; `audit: {deps: {redis: [full]}}` пропустит
его при `--mode default`.

### Условия зависимостей

`deps:` поддерживает compose-style условия запуска. Default —
`service_started` (или `service_completed_successfully` для зависимости с
`mode: oneshot`). Строковое значение = condition shorthand; null = defaults;
список = mode tags (back-compat с `--mode`); mapping = полная спецификация.

```yaml
apps:
  api:
    deps:
      postgres: service_healthy             # ждать healthcheck
      redis: ~                              # default: service_started
      init-data:
        condition: service_completed_successfully
        restart: true                       # перезапустить api при перезапуске init-data
        required: false                     # api стартует даже если init-data не поднялся
```

Эти поля проксируются в compose `depends_on.<svc>.{condition,restart,required}`.

### Exec / run

| Команда | Что |
|---|---|
| `cupli exec -c <service> -- <cmd>` | внутри запущенного контейнера. |
| `cupli run -c <service> -- <cmd>` | one-shot (`run --rm`). |
| `cupli shell -c <service>` | `/bin/bash` (или `--shell <path>`). |
| `cupli wrap -c <app> -- <cmd>` | на хосте, с экспортированным env app'а. |
| `cupli env [-c <app>] [--export]` | резолвленный env. |

### Shortcuts

| Команда | Что |
|---|---|
| `cupli sc` | список объявленных `commands:`. |
| `cupli sc <name> [args]` | запуск shortcut'а. |
| `cupli <name>` | то же, если `top_level: true`. |

### Workspace

| Команда | Что |
|---|---|
| `cupli init [-n name] [--path .] [--force] [--no-sync] [--no-ide]` | scaffold + register. Создаёт `space.cupli.yaml`, `.env`, `.locals/`; `src/apps/`, `src/bases/`, `src/mounts/` появятся лениво, когда `cupli space sync` (или другой use-case) их затребует. |
| `cupli workspace add -n <name> -f <file>` | зарегистрировать существующий space. |
| `cupli workspace list` | все зарегистрированные. `*` — активный. |
| `cupli workspace select <name>` | sticky активный. |
| `cupli workspace unselect` | сброс (cwd-detect). |
| `cupli workspace current` | что cupli использует прямо сейчас. |
| `cupli workspace remove <name>` | убрать из реестра (фс не трогает). |
| `cupli space sync [--apps/--bases/--mounts] [--pull]` | clone declared repos + опциональный pull. |
| `cupli space doctor [--strict]` | валидация paths + repos. |

### Git (по всем cloned компонентам)

| Команда | Что |
|---|---|
| `cupli git status [targets]` | таблица. `drifted`, если working tree ≠ pinned. |
| `cupli git pull [targets] [--rebase]` | параллельный pull. |
| `cupli git fetch [targets]` | параллельный fetch. |
| `cupli git checkout <branch> [-t target] [-m name=branch]` | switch с per-repo overrides. |

### Mounts

| Команда | Что |
|---|---|
| `cupli mounts list` | все mount'ы и их state (вкл. `host_bridge`). |
| `cupli mounts attach <name>` | bind в `hosted_in` apps. |
| `cupli mounts detach <name>` | снять bind. |
| `cupli mounts bridge [names]` | создать/починить `host_bridge`-симлинки. |
| `cupli mounts unbridge [names]` | удалить созданные cupli `host_bridge`-симлинки. |

### Exports

| Команда | Что |
|---|---|
| `cupli exports list` | все экспорты и их статус (`missing`/`stale`/`seeded`/`synced`). |
| `cupli exports sync [names]` | материализовать / обновить host-копии. |
| `cupli exports clean [names]` | удалить host-копии `sync` (данные `bind-seeded` сохраняются). |

### Hooks

| Команда | Что |
|---|---|
| `cupli hooks install <hooks-dir> [--scope all/apps/bases/mounts] [--target name]` | установить per-target git-hook shim'ы. |
| `cupli hooks remove [--scope] [--target]` | убрать shim'ы. |

Хук-скрипты под `<hooks-dir>/<hook-name>/*.sh` диспатчатся в контейнер
target'а. Первая строка переопределяет дефолты:

```bash
#!/usr/bin/env bash
# cupli: container=api workdir=/app shell=sh
echo "запускаюсь внутри контейнера"
```

`shell=sh` переключает in-container interpreter с `bash` (по умолчанию)
на POSIX `sh` — пригодится для alpine-образов без `bash`.

### IDE

| Команда | Что |
|---|---|
| `cupli ide setup [--target auto/vscode/pycharm/all] [--force]` | пишет JSON-schema mapping'и. `auto` идёт вверх по родителям, ища `.vscode/` / `.idea/` (останавливается на git-repo boundary), и пишет только для найденных editor'ов. |

### Диагностика

| Команда | Что |
|---|---|
| `cupli graph` | дерево bases / apps / mounts / commands. |
| `cupli dashboard [-i interval]` | live status. |
| `cupli stats [--follow]` | `docker stats` scoped to workspace. |
| `cupli explain <code>` | reference кодов ошибок. |

---

## Рецепты

### Один inline сервис без compose-файла

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

Полный файл: [`docs/examples/celery/`](docs/examples/celery/).

### Multi-repo workspace

* `repo:` + `branch:` на каждом app/mount со своим checkout'ом.
* `cupli init` клонит под `src/apps/<name>`.
* `cupli git status` агрегирует состояние.

Полный файл: [`docs/examples/multi-repo-shop/`](docs/examples/multi-repo-shop/).

### Rename compose-сервиса

```yaml
apps:
  redis:
    service: agora-redis             # compose-фрагмент называет его agora-redis
    composes: [./compose.yml]
```

### Hot-swap вендорного SDK

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

### Per-repo branch при checkout

```bash
cupli git checkout main                                 # все repo → main
cupli git checkout main -t shop-api -t shop-web         # только эти два
cupli git checkout -m shop-api=feature/x -m shop-web=main
```

### Tag-based фильтрация

```yaml
apps:
  postgres: {tags: [infra, db]}
  redis:    {tags: [infra, cache]}
  shop-api: {tags: [backend]}
```

```bash
cupli up --tag infra            # только postgres + redis
```

### Целиться в один сервис compound app'а

```bash
cupli up backend                # все сервисы app'а `backend`
cupli up celery-worker          # только этот compose-сервис из compound app'а
cupli up celery-worker celery-beat   # несколько конкретных сервисов
```

### Кастомные сети

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
      networks: [default, shared-net]   # `default` — автосеть cupli
  metrics:
    service:
      image: ...
      networks: [monitoring]
```

### Именованные тома, секреты, конфиги

Top-level `volumes:` / `secrets:` / `configs:` дословно сливаются в
`docker-compose.pre.yml`, поэтому inline-сервис может ссылаться на них без
отдельного compose-файла. Синтетический `default` не добавляется (в отличие от
`networks`), а пустой блок в вывод не попадает.

```yaml
volumes:
  minio_data:            # пустое тело == том с драйвером по умолчанию

secrets:
  ci_token:
    environment: CI_JOB_TOKEN

apps:
  minio:
    service:
      image: minio/minio
      command: server /data
      volumes: [minio_data:/data]   # ссылка на том выше
```

---

## Настройка IDE

`cupli init` и `cupli ide setup` пишут JSON-schema mapping'и для тех
editor'ов, которые обнаружили вокруг workspace'а (`auto` идёт вверх по
родителям до границы git-репозитория, ища `.vscode/` или `.idea/`).
Каждый сгенерированный `space.cupli.yaml` также несёт
`# yaml-language-server: $schema=...` директиву на первой строке —
современные редакторы подхватывают её и без config-файлов.

### VS Code

Поставь [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml).
Всё — schema-директива работает. Можно явно:

```json
// .vscode/settings.json
{
  "yaml.schemas": {
    "./space.schema.json": "space.cupli.yaml"
  }
}
```

### PyCharm / IntelliJ

В IntelliJ 2023.2+ встроенный YAML plugin понимает inline-директиву. Если нет:

`Settings → Languages & Frameworks → Schemas and DTDs → JSON Schema
Mappings → +`

* Name: `cupli space`
* Schema file: выбрать `space.schema.json` из корня репо
* File path pattern: `space.cupli.yaml` (или `*.cupli.yaml`)

### neovim с LSP

`yaml-language-server` понимает inline-директиву. Убедись, что он
включён на `*.cupli.yaml`.

### Регенерация schema

`space.schema.json` лежит в корне и генерится из Pydantic-моделей:

```bash
make schema       # или: uv run python scripts/generate_schema.py
```

Запускай после изменений в `src/cupli/domain/models.py`.

---

## Ограничения

* **Один project за раз.** Один `space.cupli.yaml` = ровно один
  docker-compose project. Чтобы скомпоновать два cupli workspace'а —
  шарьте infra через external networks.
* **Без нативного Kubernetes.** Compose-only.
* **Без удалённого build farm'а.** Build'ы локальные через `docker compose`.
* **Без secrets management.** `.env.local` (gitignored) + `${VAR}`
  подстановка. Vault'а в коробке нет.
* **Schema v1.** Несовместимые изменения гейтятся на `schema_version`.
  `cupli upgrade-config` — placeholder под миграции.

---

## Troubleshooting + коды ошибок

`cupli explain <code>` печатает полное описание. Шпаргалка:

| Код | Смысл |
|---|---|
| `E001` | Space-файл не найден. |
| `E002` | Validation failed (pydantic). Per-field сообщения с `file:line:col`. |
| `E003` | Пустой / только-комментарии space-файл. |
| `E004` | YAML syntax error. |
| `E014` | Цикл в interpolation переменных. |
| `E015` | User-переменная пересекается с reserved auto-var. |
| `E016` | Unknown `${VAR}` при `--strict-vars`. |
| `E017` | `git clone` упал. |
| `E020` | Unknown имя (app / mount / target / space). |
| `E028` | Unknown cupli error code (catch-all). |
| `E029` | Space-файл уже существует. |
| `E030` | Per-component env-var name collision (например, `shop-api` и `shop_api` оба → `SHOP_API_APP_PATH`). |

Для `cupli space doctor` и `cupli config` вывод теперь содержит
per-field summary с source locations.
