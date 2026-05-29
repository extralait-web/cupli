"""Tests for :mod:`cupli.services.compose_service`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from cupli.core.loader import load_space
from cupli.domain.errors import CupliError
from cupli.services.compose_service import (
    build_argv,
    make_plan,
    render_overrides,
    shared_volume_inits,
    write_env_file,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write(target: Path, body: str) -> Path:
    target.write_text(body, encoding="utf-8")
    return target


def test_render_overrides_creates_both_files(tmp_path: Path) -> None:
    """``render_overrides`` writes pre + post under ``.locals/<space>/state/``."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    pre_path, post_path, _ = render_overrides(resolved)
    assert pre_path.exists()
    assert post_path.exists()
    assert pre_path.parent.parent.parent == tmp_path / ".locals"


def test_generated_files_carry_do_not_edit_banner(tmp_path: Path) -> None:
    """Every cupli-generated YAML / env file starts with the AUTO-GENERATED banner."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    pre_path, post_path, _ = render_overrides(resolved)
    env_path = write_env_file(resolved)
    for path in (pre_path, post_path, env_path):
        head = path.read_text(encoding="utf-8").splitlines()[:5]
        assert any("AUTO-GENERATED" in line for line in head), f"missing banner in {path}"
        assert any("DO NOT EDIT" in line for line in head), f"missing banner in {path}"


def test_pre_override_declares_network(tmp_path: Path) -> None:
    """The pre-override defines the project network using ``${NETWORK}``."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert data["networks"]["default"]["name"] == "demo"


def test_pre_override_renders_top_level_volumes(tmp_path: Path) -> None:
    """A top-level ``volumes:`` block is copied verbatim into the pre-override."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\nvolumes:\n  minio_data:\n    driver: local\n",
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert data["volumes"]["minio_data"] == {"driver": "local"}


def test_pre_override_renders_top_level_secrets_and_configs(tmp_path: Path) -> None:
    """Top-level ``secrets:`` and ``configs:`` blocks pass through verbatim."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\n"
        "secrets:\n  ci_token:\n    environment: CI_JOB_TOKEN\n"
        "configs:\n  app_cfg:\n    file: ./cfg.yml\n",
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert data["secrets"]["ci_token"] == {"environment": "CI_JOB_TOKEN"}
    assert data["configs"]["app_cfg"] == {"file": "./cfg.yml"}


def test_pre_override_named_volume_with_null_body(tmp_path: Path) -> None:
    """``minio_data:`` with no body renders as an empty mapping (default driver)."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\nvolumes:\n  minio_data:\n",
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert data["volumes"] == {"minio_data": {}}


def test_pre_override_omits_empty_top_level_blocks(tmp_path: Path) -> None:
    """No ``volumes`` / ``secrets`` / ``configs`` keys appear when none are declared."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert "volumes" not in data
    assert "secrets" not in data
    assert "configs" not in data


def test_pre_override_top_level_blocks_have_no_default(tmp_path: Path) -> None:
    """Unlike ``networks``, the new blocks get no synthetic ``default`` entry."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\nvolumes:\n  minio_data: {}\n",
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert "default" not in data["volumes"]


def test_pre_override_defaults_container_name(tmp_path: Path) -> None:
    """Every declared service gets ``container_name: <space>-<svc>`` in the pre-override.

    The pre-override is loaded *before* user compose-fragments, so any
    ``container_name`` they declare overrides this default via compose merge.
    """
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n  api:\n    image: api\n  agora-redis:\n    image: redis\n",
        encoding="utf-8",
    )
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\napps:\n"
            f"  api:\n    composes: ['{compose}']\n"
            f"  redis:\n    service: agora-redis\n    composes: ['{compose}']\n"
        ),
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert data["services"]["api"]["container_name"] == "demo-api"
    assert data["services"]["agora-redis"]["container_name"] == "demo-agora-redis"


def test_pre_override_strips_duplicate_project_prefix(tmp_path: Path) -> None:
    """Services already prefixed with ``<space>-`` keep their name (no double prefix)."""
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n  demo-api:\n    image: api\n  demo:\n    image: meta\n",
        encoding="utf-8",
    )
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (f"name: demo\napps:\n  demo-api:\n    composes: ['{compose}']\n  demo:\n    composes: ['{compose}']\n"),
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert data["services"]["demo-api"]["container_name"] == "demo-api"
    assert data["services"]["demo"]["container_name"] == "demo"


def test_pre_override_skips_services_without_compose(tmp_path: Path) -> None:
    """The pre-override never invents service blocks for apps that lack a compose-fragment."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  ghost: {}\n",
    )
    resolved = load_space(space_file)
    pre_path, _, _ = render_overrides(resolved)
    data = yaml.safe_load(pre_path.read_text())
    assert "services" not in data


def _write_compose(tmp_path: Path, *service_names: str) -> Path:
    """Write a minimal compose-fragment declaring each service with an image."""
    services_yaml = "\n".join(f"  {name}:\n    image: scratch:latest" for name in service_names)
    compose = tmp_path / "compose.yml"
    compose.write_text(f"services:\n{services_yaml}\n", encoding="utf-8")
    return compose


def test_post_override_injects_mount_volumes(tmp_path: Path) -> None:
    """Each mount/host pair appears as a ``services.<svc>.volumes`` entry."""
    compose = _write_compose(tmp_path, "api", "migrate")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            f"  api:\n    composes: ['{compose}']\n"
            f"  migrate:\n    composes: ['{compose}']\n"
            "mounts:\n"
            "  sdk:\n"
            "    hosted_in: [api, migrate]\n"
            "    exec_path: /opt/sdk\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert data["services"]["api"]["volumes"] == [f"{resolved.mounts['sdk'].path}:/opt/sdk:rw"]
    assert data["services"]["migrate"]["volumes"] == [f"{resolved.mounts['sdk'].path}:/opt/sdk:rw"]


def test_post_override_injects_bind_seeded_export_volume(tmp_path: Path) -> None:
    """A ``bind-seeded`` export injects a host bind at its ``exec_path``."""
    compose = _write_compose(tmp_path, "web")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            f"  web:\n    composes: ['{compose}']\n"
            "exports:\n"
            "  nm:\n"
            "    from: web\n"
            "    exec_path: /app/node_modules\n"
            "    path: ${WEB_APP_PATH}/node_modules\n"
            "    strategy: bind-seeded\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    volumes = data["services"]["web"]["volumes"]
    assert {"type": "bind", "source": str(resolved.exports["nm"].path), "target": "/app/node_modules"} in volumes


def test_post_override_skips_sync_export_volume(tmp_path: Path) -> None:
    """A ``sync`` export keeps the named volume — no bind is injected."""
    compose = _write_compose(tmp_path, "web")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            f"  web:\n    composes: ['{compose}']\n"
            "exports:\n"
            "  nm:\n"
            "    from: web\n"
            "    exec_path: /app/node_modules\n"
            "    path: ${WEB_APP_PATH}/node_modules\n"
            "    strategy: sync\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert "volumes" not in data.get("services", {}).get("web", {})


def test_post_override_injects_per_service_environment(tmp_path: Path) -> None:
    """Each app's ``vars:`` lands in ``services.<svc>.environment``."""
    compose = _write_compose(tmp_path, "api", "worker")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "vars:\n"
            "  STACK_ENV: dev\n"
            "apps:\n"
            "  api:\n"
            f"    composes: ['{compose}']\n"
            "    vars:\n"
            "      LOG_LEVEL: debug\n"
            "      REGION: eu-west\n"
            "  worker:\n"
            f"    composes: ['{compose}']\n"
            "    vars:\n"
            "      LOG_LEVEL: info\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    api_env = data["services"]["api"]["environment"]
    assert api_env["LOG_LEVEL"] == "debug"
    assert api_env["REGION"] == "eu-west"
    assert api_env["STACK_ENV"] == "dev"  # inherited from space scope
    # Auto-vars must not leak into the container env.
    assert "SPACE_PATH" not in api_env
    assert "APPS_PATH" not in api_env
    assert "APP_NAME" not in api_env
    assert "APP_PATH" not in api_env
    # Workers have their own env block.
    assert data["services"]["worker"]["environment"]["LOG_LEVEL"] == "info"


def test_post_override_injects_cross_file_depends_on(tmp_path: Path) -> None:
    """Declared ``apps[*].deps`` show up as compose ``depends_on``."""
    compose = _write_compose(tmp_path, "api", "worker")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\napps:\n"
            f"  api:\n    composes: ['{compose}']\n    deps:\n      worker: [default]\n"
            f"  worker:\n    composes: ['{compose}']\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert data["services"]["api"]["depends_on"] == {
        "worker": {"condition": "service_started"},
    }


def test_post_override_honours_dep_condition_shorthand(tmp_path: Path) -> None:
    """``deps: {worker: service_healthy}`` lands in compose as the condition."""
    compose = _write_compose(tmp_path, "api", "worker")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\napps:\n"
            f"  api:\n    composes: ['{compose}']\n    deps:\n      worker: service_healthy\n"
            f"  worker:\n    composes: ['{compose}']\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert data["services"]["api"]["depends_on"] == {
        "worker": {"condition": "service_healthy"},
    }


def test_post_override_forwards_restart_and_required(tmp_path: Path) -> None:
    """The full ``DepSpec`` form forwards ``restart`` / ``required`` to compose."""
    compose = _write_compose(tmp_path, "api", "worker")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\napps:\n"
            f"  api:\n    composes: ['{compose}']\n    deps:\n"
            "      worker:\n        condition: service_healthy\n        restart: true\n        required: false\n"
            f"  worker:\n    composes: ['{compose}']\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    entry = data["services"]["api"]["depends_on"]["worker"]
    assert entry["condition"] == "service_healthy"
    assert entry["restart"] is True
    assert entry["required"] is False


def test_write_env_file_dumps_resolved_vars(tmp_path: Path) -> None:
    """``write_env_file`` writes one ``KEY=VALUE`` per resolved space variable."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    env_path = write_env_file(resolved)
    body = env_path.read_text(encoding="utf-8")
    assert "SPACE_NAME=demo" in body
    assert "NETWORK=demo" in body


def test_write_env_file_strips_process_env_forwards(tmp_path: Path) -> None:
    """Forwarded host vars (PATH, HOME, …) must not leak into ``override.env``.

    They're kept in ``space_vars`` for cupli-side YAML substitution but are
    irrelevant to docker compose, which inherits them from the parent shell.
    """
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    env_path = write_env_file(resolved)
    keys = {line.split("=", 1)[0] for line in env_path.read_text(encoding="utf-8").splitlines() if "=" in line}
    for leaked in ("PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_ALL", "SSH_AUTH_SOCK"):
        assert leaked not in keys, f"{leaked} leaked into override.env"


def test_post_override_skips_undeclared_service(tmp_path: Path) -> None:
    """Apps with a service name absent from every compose-fragment are skipped.

    Otherwise ``override.post`` would create a shadow service block without
    ``image`` / ``build`` and ``docker compose config`` would reject it.
    """
    (tmp_path / "compose.yml").write_text(
        "services:\n  agora-redis:\n    image: redis\n",
        encoding="utf-8",
    )
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (f"name: demo\napps:\n  redis:\n    composes: ['{tmp_path / 'compose.yml'}']\n    vars:\n      FOO: bar\n"),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    services_block = (data or {}).get("services") or {}
    assert "redis" not in services_block


def test_post_override_attaches_default_network(tmp_path: Path) -> None:
    """Every declared service gets ``networks: [default]`` in the post-override."""
    (tmp_path / "compose.yml").write_text(
        "services:\n  api:\n    image: api\n",
        encoding="utf-8",
    )
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        f"name: demo\napps:\n  api:\n    composes: ['{tmp_path / 'compose.yml'}']\n",
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert data["services"]["api"]["networks"] == ["default"]


def test_post_override_handles_explicit_service_name(tmp_path: Path) -> None:
    """``apps.<name>.service`` is honoured: env injection lands on the real compose service."""
    (tmp_path / "compose.yml").write_text(
        "services:\n  agora-redis:\n    image: redis\n",
        encoding="utf-8",
    )
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  redis:\n"
            "    service: agora-redis\n"
            f"    composes: ['{tmp_path / 'compose.yml'}']\n"
            "    vars:\n"
            "      FOO: bar\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert "redis" not in data["services"]
    assert data["services"]["agora-redis"]["environment"] == {"FOO": "bar"}
    assert "default" in data["services"]["agora-redis"]["networks"]


def test_service_inline_shorthand_creates_single_service(tmp_path: Path) -> None:
    """``service:`` as a dict creates one inline service named after the app — no compose file needed."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  redis:\n"
            "    service:\n"
            "      image: redis:7-alpine\n"
            "      command: [redis-server, --appendonly, 'yes']\n"
            "    vars:\n"
            "      LOG_LEVEL: info\n"
        ),
    )
    resolved = load_space(space_file)
    pre_path, post_path, inline_path = render_overrides(resolved)
    assert inline_path is not None
    inline = yaml.safe_load(inline_path.read_text())
    assert inline["services"]["redis"]["image"] == "redis:7-alpine"
    pre = yaml.safe_load(pre_path.read_text())
    post = yaml.safe_load(post_path.read_text())
    assert pre["services"]["redis"]["container_name"] == "demo-redis"
    assert post["services"]["redis"]["environment"] == {"LOG_LEVEL": "info"}
    assert "default" in post["services"]["redis"]["networks"]


def test_service_string_still_renames_compose_service(tmp_path: Path) -> None:
    """``service: 'name'`` (string form) keeps the old behaviour: bind to existing compose service."""
    compose = _write_compose(tmp_path, "agora-redis")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\napps:\n"
            f"  redis:\n    service: agora-redis\n    composes: ['{compose}']\n    vars:\n      FOO: bar\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert "redis" not in data["services"]
    assert data["services"]["agora-redis"]["environment"] == {"FOO": "bar"}


def test_inline_compose_creates_service_from_scratch(tmp_path: Path) -> None:
    """Compose-syntax fields under ``services.<svc>`` create a fully-inline service.

    No external compose-fragment is needed: cupli writes the spec to
    ``docker-compose.inline.yml`` which joins the COMPOSE_FILE chain.
    """
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  worker:\n"
            "    services:\n"
            "      worker:\n"
            "        image: python:3.12\n"
            "        command: [python, -m, worker]\n"
            "        vars:\n"
            "          LOG_LEVEL: info\n"
        ),
    )
    resolved = load_space(space_file)
    _, _, inline_path = render_overrides(resolved)
    assert inline_path is not None
    inline = yaml.safe_load(inline_path.read_text())
    spec = inline["services"]["worker"]
    assert spec["image"] == "python:3.12"
    assert spec["command"] == ["python", "-m", "worker"]
    assert "vars" not in spec  # cupli-only fields stripped from inline output


def test_inline_service_is_declared_for_inject(tmp_path: Path) -> None:
    """An inline-defined service is treated as declared for the cupli inject pipeline."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  worker:\n"
            "    services:\n"
            "      worker:\n"
            "        image: python:3.12\n"
            "        vars:\n"
            "          LOG_LEVEL: info\n"
        ),
    )
    resolved = load_space(space_file)
    pre_path, post_path, _ = render_overrides(resolved)
    pre = yaml.safe_load(pre_path.read_text())
    post = yaml.safe_load(post_path.read_text())
    assert pre["services"]["worker"]["container_name"] == "demo-worker"
    assert post["services"]["worker"]["environment"] == {"LOG_LEVEL": "info"}
    assert "default" in post["services"]["worker"]["networks"]


def test_inline_omitted_when_no_compose_fields(tmp_path: Path) -> None:
    """Without compose-syntax fields, no inline file is generated."""
    compose = _write_compose(tmp_path, "api")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\napps:\n  api:\n"
            f"    composes: ['{compose}']\n"
            "    services:\n      api:\n        vars: {FOO: bar}\n"
        ),
    )
    resolved = load_space(space_file)
    _, _, inline_path = render_overrides(resolved)
    assert inline_path is None


def test_services_map_injects_env_and_ports_into_all(tmp_path: Path) -> None:
    """``apps.<name>.services`` map drives env/ports injection on every listed service."""
    compose = _write_compose(tmp_path, "backend", "celery-worker", "celery-beat")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  backend:\n"
            f"    composes: ['{compose}']\n"
            "    vars:\n"
            "      DATABASE_URL: postgres://x\n"
            "    ports:\n"
            "      - '8000:8000'\n"
            "    services:\n"
            "      backend: {}\n"
            "      celery-worker:\n"
            "        vars:\n"
            "          CELERY_LOG_LEVEL: info\n"
            "        ports: []\n"
            "      celery-beat:\n"
            "        ports: []\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    backend_env = data["services"]["backend"]["environment"]
    worker_env = data["services"]["celery-worker"]["environment"]
    beat_env = data["services"]["celery-beat"]["environment"]
    assert backend_env["DATABASE_URL"] == "postgres://x"
    assert worker_env["DATABASE_URL"] == "postgres://x"  # inherited from app vars
    assert worker_env["CELERY_LOG_LEVEL"] == "info"  # per-service override
    assert beat_env["DATABASE_URL"] == "postgres://x"
    assert data["services"]["backend"]["ports"] == ["8000:8000"]  # app-level ports
    assert "ports" not in data["services"]["celery-worker"]  # explicit empty disables
    assert "ports" not in data["services"]["celery-beat"]


def test_services_map_primary_service_drives_depends_on(tmp_path: Path) -> None:
    """Cross-app ``deps`` target the PRIMARY service of the dependency."""
    compose = _write_compose(tmp_path, "backend", "celery-worker", "redis")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  redis:\n"
            f"    composes: ['{compose}']\n"
            "  backend:\n"
            f"    composes: ['{compose}']\n"
            "    deps:\n      redis: [default]\n"
            "    services:\n      backend: {}\n      celery-worker: {}\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert data["services"]["backend"]["depends_on"] == {"redis": {"condition": "service_started"}}
    assert data["services"]["celery-worker"]["depends_on"] == {"redis": {"condition": "service_started"}}


def test_service_and_services_are_mutually_exclusive(tmp_path: Path) -> None:
    """Declaring both ``service:`` and ``services:`` raises ``E002``."""
    compose = _write_compose(tmp_path, "backend")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  app:\n"
            f"    composes: ['{compose}']\n"
            "    service: backend\n"
            "    services:\n      backend: {}\n"
        ),
    )
    with pytest.raises(CupliError) as exc:
        load_space(space_file)
    assert exc.value.code == "E002"


def test_post_override_injects_ports(tmp_path: Path) -> None:
    """``apps.<name>.ports`` lands in ``services.<svc>.ports`` of the post-override."""
    compose = _write_compose(tmp_path, "api")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "vars:\n"
            "  API_PORT: '8000'\n"
            "apps:\n"
            "  api:\n"
            "    service: api\n"
            f"    composes: ['{compose}']\n"
            "    ports:\n"
            "      - '${API_PORT}:8000'\n"
            "      - '127.0.0.1:5555:5555'\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert data["services"]["api"]["ports"] == ["8000:8000", "127.0.0.1:5555:5555"]


def test_post_override_skips_apps_without_ports(tmp_path: Path) -> None:
    """Apps without ``ports:`` produce no ``ports`` key in the post-override."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api:\n    service: api\n",
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert data == {} or "ports" not in data.get("services", {}).get("api", {})


def test_write_env_file_emits_per_component_paths(tmp_path: Path) -> None:
    """Per-component ``<NAME>_{APP,MOUNT,BASE}_PATH`` vars land in the env file."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "bases:\n"
            "  pyrt: {}\n"
            "apps:\n"
            "  shop-api:\n"
            "    bases: [pyrt]\n"
            "mounts:\n"
            "  shared-sdk:\n"
            "    hosted_in: [shop-api]\n"
            "    exec_path: /opt/sdk\n"
        ),
    )
    resolved = load_space(space_file)
    env_path = write_env_file(resolved)
    body = env_path.read_text(encoding="utf-8")
    apps_dir = str(tmp_path / "src" / "apps" / "shop-api")
    bases_dir = str(tmp_path / "src" / "bases" / "pyrt")
    mounts_dir = str(tmp_path / "src" / "mounts" / "shared-sdk")
    assert f"SHOP_API_APP_PATH={apps_dir}" in body
    assert f"PYRT_BASE_PATH={bases_dir}" in body
    assert f"SHARED_SDK_MOUNT_PATH={mounts_dir}" in body


def test_write_env_file_collision_raises_e030(tmp_path: Path) -> None:
    """Two components whose names normalise the same way raise E030."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  shop-api: {}\n  shop_api: {}\n",
    )
    resolved = load_space(space_file)
    with pytest.raises(CupliError) as exc:
        write_env_file(resolved)
    assert exc.value.code == "E030"
    assert "SHOP_API_APP_PATH" in str(exc.value)


def test_make_plan_chains_pre_user_post_files(tmp_path: Path) -> None:
    """Compose -f order is pre-override → app composes → post-override."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (f"name: demo\napps:\n  api:\n    composes: [{tmp_path / 'docker-compose.yml'}]\n"),
    )
    (tmp_path / "docker-compose.yml").write_text("services:\n  api:\n    image: x\n")
    resolved = load_space(space_file)
    plan = make_plan(resolved)
    names = [path.name for path in plan.compose_files]
    assert names[0] == "docker-compose.pre.yml"
    assert names[-1] == "docker-compose.post.yml"
    assert "docker-compose.yml" in names[1:-1]


def test_build_argv_assembles_expected_invocation(tmp_path: Path) -> None:
    """``build_argv`` keeps the argv minimal — compose state lives in env vars."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api:\n    service:\n      image: alpine:3.20\n",
    )
    resolved = load_space(space_file)
    plan = make_plan(resolved)
    argv = build_argv(plan, ["up", "-d"])
    assert argv[:2] == ["docker", "compose"]
    # --project-name / --project-directory / -f flags moved into COMPOSE_*.
    assert "--project-name" not in argv
    assert "--project-directory" not in argv
    assert "-f" not in argv
    # --env-file stays on argv for compose < 2.24 compatibility.
    assert "--env-file" in argv
    assert argv[-2:] == ["up", "-d"]


def test_make_plan_emits_all_managed_services_of_compound_app(tmp_path: Path) -> None:
    """A compound app with three services contributes all three to ``plan.services``.

    Previously only the primary (first key) was emitted, so ``docker compose up``
    started one container instead of three.
    """
    compose = _write_compose(tmp_path, "backend-1", "backend-2", "backend-3")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  backend:\n"
            f"    composes: ['{compose}']\n"
            "    services:\n"
            "      backend-1: {}\n"
            "      backend-2: {}\n"
            "      backend-3: {}\n"
        ),
    )
    resolved = load_space(space_file)
    plan = make_plan(resolved)
    assert plan.services == ("backend-1", "backend-2", "backend-3")


def test_make_plan_with_tag_scopes_overrides_to_selected_apps(tmp_path: Path) -> None:
    """``--tag`` narrows pre/post/inline to selected apps; unselected services are not stubbed.

    Regression: previously pre wrote ``container_name`` for every declared
    service across all apps, so when a non-selected app's compose-fragment
    was excluded from the ``-f`` chain, compose saw an orphan service block
    (no image, no build) and refused the merged document.
    """
    back_compose = tmp_path / "back.yml"
    back_compose.write_text("services:\n  api:\n    image: api:latest\n", encoding="utf-8")
    front_compose = tmp_path / "front.yml"
    front_compose.write_text("services:\n  web:\n    image: web:latest\n", encoding="utf-8")
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  api:\n"
            f"    composes: ['{back_compose}']\n"
            "    tags: [back]\n"
            "  web:\n"
            f"    composes: ['{front_compose}']\n"
            "    tags: [front]\n"
        ),
    )
    resolved = load_space(space_file)
    plan = make_plan(resolved, tags=["back"])
    assert plan.services == ("api",)
    pre = yaml.safe_load(next(p for p in plan.compose_files if p.name == "docker-compose.pre.yml").read_text())
    pre_services = (pre.get("services") or {}).keys()
    assert "api" in pre_services
    assert "web" not in pre_services


def test_make_plan_oneshot_dep_emits_service_completed_successfully(tmp_path: Path) -> None:
    """A dep on a ``mode: oneshot`` app is wired with ``service_completed_successfully``.

    Without this, an ``api`` that depends on ``migrate`` starts in parallel
    with the migration instead of waiting for it to exit cleanly.
    """
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  migrate:\n"
            "    mode: oneshot\n"
            "    service:\n"
            "      image: alpine:3.20\n"
            "      command: ['echo', 'migrated']\n"
            "  api:\n"
            "    deps: [migrate]\n"
            "    service:\n"
            "      image: alpine:3.20\n"
        ),
    )
    resolved = load_space(space_file)
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    api_dep = data["services"]["api"]["depends_on"]
    assert api_dep == {"migrate": {"condition": "service_completed_successfully"}}


def test_make_plan_targeting_one_service_of_compound_app(tmp_path: Path) -> None:
    """``cupli up fleet-2`` on a compound app starts only ``fleet-2``.

    Regression: the old plan emitted every managed service of the seed app,
    so the user could not target a single instance of a multi-service app.
    """
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  fleet:\n"
            "    services:\n"
            "      fleet-1: {image: alpine:3.20}\n"
            "      fleet-2: {image: alpine:3.20}\n"
            "      fleet-3: {image: alpine:3.20}\n"
        ),
    )
    resolved = load_space(space_file)
    plan = make_plan(resolved, services=["fleet-2"])
    assert plan.services == ("fleet-2",)


def test_make_plan_app_name_emits_all_managed_services(tmp_path: Path) -> None:
    """Naming the app (``fleet``) starts every service the app owns."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (
            "name: demo\n"
            "apps:\n"
            "  fleet:\n"
            "    services:\n"
            "      fleet-1: {image: alpine:3.20}\n"
            "      fleet-2: {image: alpine:3.20}\n"
        ),
    )
    resolved = load_space(space_file)
    plan = make_plan(resolved, services=["fleet"])
    assert plan.services == ("fleet-1", "fleet-2")


def test_make_plan_raises_e031_when_service_not_declared(tmp_path: Path) -> None:
    """Missing compose-fragment surfaces as a precise CupliError, not a compose failure."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: demo\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    with pytest.raises(CupliError) as exc:
        make_plan(resolved)
    assert exc.value.code == "E031"
    assert "api" in str(exc.value)


def test_build_env_exposes_compose_state(tmp_path: Path) -> None:
    """``build_env`` populates ``COMPOSE_FILE``/``PROJECT_NAME``/``PROJECT_DIRECTORY``."""
    from cupli.services.compose_service import COMPOSE_PATH_SEP, build_env

    space_file = _write(
        tmp_path / "space.cupli.yaml",
        (f"name: demo\napps:\n  api:\n    composes: [{tmp_path / 'docker-compose.yml'}]\n"),
    )
    (tmp_path / "docker-compose.yml").write_text("services:\n  api:\n    image: x\n")
    resolved = load_space(space_file)
    plan = make_plan(resolved)
    env = build_env(plan)
    assert env["COMPOSE_PROJECT_NAME"] == "demo"
    assert env["COMPOSE_PROJECT_DIRECTORY"] == str(tmp_path.resolve())
    assert env["COMPOSE_PATH_SEPARATOR"] == COMPOSE_PATH_SEP
    files = env["COMPOSE_FILE"].split(COMPOSE_PATH_SEP)
    assert any("docker-compose.pre.yml" in path for path in files)
    assert any("docker-compose.post.yml" in path for path in files)
    assert any("docker-compose.yml" in path for path in files)


def test_shared_volume_inits_detects_volume_shared_by_multiple_services() -> None:
    """A named volume mounted by >=2 services is returned for one-shot init (H2)."""
    config = {
        "services": {
            "web": {"image": "img:dev", "volumes": [{"type": "volume", "source": "venv", "target": "/app/.venv"}]},
            "worker": {"image": "img:dev", "volumes": [{"type": "volume", "source": "venv", "target": "/app/.venv"}]},
            "beat": {"image": "img:dev", "volumes": [{"type": "volume", "source": "venv", "target": "/app/.venv"}]},
            "solo": {"image": "img:dev", "volumes": [{"type": "volume", "source": "cache", "target": "/cache"}]},
        },
        "volumes": {"venv": {"name": "demo_venv"}, "cache": {"name": "demo_cache"}},
    }
    inits = shared_volume_inits(config)
    assert inits == [("demo_venv", "/app/.venv", "img:dev")]  # `cache` (1 service) excluded


def test_shared_volume_inits_empty_for_no_sharing() -> None:
    """No shared named volume → nothing to pre-initialise."""
    config = {
        "services": {"web": {"image": "i", "volumes": [{"type": "volume", "source": "v", "target": "/x"}]}},
        "volumes": {"v": {"name": "demo_v"}},
    }
    assert shared_volume_inits(config) == []
    assert shared_volume_inits(None) == []
