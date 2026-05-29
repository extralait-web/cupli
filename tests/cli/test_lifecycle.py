"""Tests for the compose lifecycle CLI commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cupli.cli.root import app
from cupli.core import registry

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the registry to a per-test file."""
    registry_path = tmp_path / "spaces.json"
    monkeypatch.setattr(registry, "spaces_registry_path", lambda: registry_path)
    return registry_path


@pytest.fixture()
def runner() -> CliRunner:
    """Fresh ``CliRunner`` per test."""
    return CliRunner()


@pytest.fixture()
def captured_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture the argv handed to ``compose_service.invoke``."""
    recorded: list[list[str]] = []

    def _record(_plan: object, argv: list[str]) -> None:
        recorded.append(argv)

    monkeypatch.setattr("cupli.cli.lifecycle.invoke", _record)
    return recorded


def _space(tmp_path: Path) -> Path:
    space = tmp_path / "space.cupli.yaml"
    space.write_text(
        "name: demo\napps:\n  api:\n    service:\n      image: alpine:3.20\n",
        encoding="utf-8",
    )
    return space


def test_up_includes_detach_and_build_flags(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli up -d --build`` builds first (separate step), then ``up`` with ``-d`` / ``--pull``.

    ``--build`` is no longer forwarded to ``up``: cupli runs an explicit
    ``build`` first so bind-seed / shared-volume prep see a real image, then
    ``up`` without ``--build``.
    """
    _ = isolated_registry
    space = _space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "up", "-d", "--build"])
    assert result.exit_code == 0, result.stdout
    verbs = [argv[0] for argv in captured_argv]
    assert "build" in verbs  # build runs as its own step
    last = captured_argv[-1]
    assert last[0] == "up"
    assert "-d" in last
    assert "--build" not in last  # not forwarded to up anymore
    assert "--pull" in last
    assert "missing" in last
    assert "api" in last


def test_up_forwards_unknown_flags_to_compose(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """An unknown flag like ``--force-recreate`` is forwarded to docker compose."""
    _ = isolated_registry
    space = _space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "up", "-d", "--force-recreate", "api"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "up"
    assert "--force-recreate" in last
    assert "api" in last  # real service name is NOT swallowed as a flag


def test_up_pull_policy_can_be_overridden(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``--pull always`` lands in the argv."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "up", "--pull", "always"])
    last = captured_argv[-1]
    assert ["--pull", "always"] == last[last.index("--pull") : last.index("--pull") + 2]


def test_stop_emits_stop_argv(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli stop`` builds a ``stop <svc>`` argv."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "stop"])
    assert captured_argv[-1][0] == "stop"
    assert "api" in captured_argv[-1]


def test_restart_default_calls_restart(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli restart`` (no ``--hard``) calls compose ``restart``."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "restart"])
    assert captured_argv[-1][0] == "restart"


def test_restart_hard_does_down_then_up(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli restart --hard`` runs ``down --remove-orphans`` then ``up -d``."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "restart", "--hard"])
    assert captured_argv[-2][0] == "down"
    assert "--remove-orphans" in captured_argv[-2]
    assert captured_argv[-1][0] == "up"
    assert "-d" in captured_argv[-1]


def test_down_with_volumes_and_images_propagates_flags(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli down -v --images`` adds ``--volumes`` and ``--rmi local``."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "down", "-v", "--images"])
    last = captured_argv[-1]
    assert last[0] == "down"
    assert "--volumes" in last
    assert "--rmi" in last
    assert "local" in last


def test_down_forwards_named_service(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli down api`` forwards the service name so only that container goes down.

    Earlier versions silently dropped the positional and tore the whole stack
    down — regression test for that bug.
    """
    _ = isolated_registry
    space = _space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "down", "api"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "down"
    assert "api" in last


def test_down_without_service_remains_workspace_wide(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli down`` (no service) still tears the whole workspace down."""
    _ = isolated_registry
    space = _space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "down"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "down"
    assert "--remove-orphans" in last
    # No stray service names beyond the cupli flags
    assert all(token.startswith("-") or token in {"down", "--remove-orphans", "local"} for token in last)


def _space_with_deps(tmp_path: Path) -> Path:
    """Two-app workspace: ``api`` depends on ``db`` via ``apps[*].deps``."""
    space = tmp_path / "space.cupli.yaml"
    space.write_text(
        "\n".join(
            [
                "name: demo",
                "apps:",
                "  db:",
                "    service:",
                "      image: postgres:16",
                "  api:",
                "    service:",
                "      image: alpine:3.20",
                "    deps:",
                "      db: {}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return space


def test_restart_named_service_skips_dep_closure(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli restart api`` restarts only ``api`` — ``db`` (a dep) stays untouched.

    Earlier versions used the closure-expanded ``plan.services`` and would
    restart the whole dep chain whenever a single service was named. The
    per-service verbs must act exactly on what the user asked for.
    """
    _ = isolated_registry
    space = _space_with_deps(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "restart", "api"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "restart"
    assert "api" in last
    assert "db" not in last  # dep must NOT be pulled in by closure


def test_restart_without_args_still_targets_full_workspace(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli restart`` (no names) keeps the closure-expanded plan."""
    _ = isolated_registry
    space = _space_with_deps(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "restart"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "restart"
    assert "api" in last
    assert "db" in last


def test_stop_named_service_skips_dep_closure(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli stop api`` stops only ``api`` — ``db`` stays running."""
    _ = isolated_registry
    space = _space_with_deps(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "stop", "api"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "stop"
    assert "api" in last
    assert "db" not in last


def test_down_named_service_skips_dep_closure(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli down api`` removes only ``api`` — ``db`` is not collateral damage."""
    _ = isolated_registry
    space = _space_with_deps(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "down", "api"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "down"
    assert "api" in last
    assert "db" not in last


def test_build_named_service_skips_dep_closure(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli build api`` builds only ``api`` — deps' images are not rebuilt."""
    _ = isolated_registry
    space = _space_with_deps(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "build", "api"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "build"
    assert "api" in last
    assert "db" not in last


def test_pull_named_service_skips_dep_closure(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli pull api`` pulls only ``api`` — deps' images are not re-pulled."""
    _ = isolated_registry
    space = _space_with_deps(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "pull", "api"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "pull"
    assert "api" in last
    assert "db" not in last


def test_up_named_service_still_starts_dep_closure(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli up api`` keeps the closure-expanded plan — deps must come up first."""
    _ = isolated_registry
    space = _space_with_deps(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "up", "-d", "api"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "up"
    assert "api" in last
    assert "db" in last  # dep IS pulled into the up plan


def test_ps_emits_ps_argv(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli ps`` builds a ``ps <svc>`` argv."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "ps"])
    assert captured_argv[-1][0] == "ps"


def test_logs_with_follow_and_tail(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli logs <svc> -f --tail N`` propagates the flags."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "logs", "api", "-f", "--tail", "50"])
    last = captured_argv[-1]
    assert last[0] == "logs"
    assert "--tail" in last
    assert "50" in last
    assert "-f" in last
    assert "api" in last


def test_logs_without_service_streams_all(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """Omitting the service name still produces a ``logs`` argv (no name)."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "logs", "--tail", "10"])
    last = captured_argv[-1]
    assert last[0] == "logs"
    assert "api" not in last


def test_build_with_no_cache_and_pull(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli build --no-cache --pull`` propagates both flags."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "build", "--no-cache", "--pull"])
    last = captured_argv[-1]
    assert last[0] == "build"
    assert "--no-cache" in last
    assert "--pull" in last


def test_pull_command_emits_pull_argv(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli pull`` builds a ``pull <svc>`` argv."""
    _ = isolated_registry
    space = _space(tmp_path)
    runner.invoke(app, ["-f", str(space), "pull"])
    assert captured_argv[-1][0] == "pull"


def test_invalid_mode_reports_user_error(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """An unsupported ``--mode`` value surfaces ``E020`` and skips invoke."""
    _ = isolated_registry
    space = _space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "up", "--mode", "bogus"])
    assert result.exit_code != 0
    assert not captured_argv
