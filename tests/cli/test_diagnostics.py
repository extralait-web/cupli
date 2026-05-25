"""Tests for ``cupli graph`` / ``cupli stats``."""

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


def _space(tmp_path: Path, body: str) -> Path:
    space = tmp_path / "space.cupli.yaml"
    space.write_text(body, encoding="utf-8")
    return space


def test_graph_renders_apps_and_deps(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli graph`` renders the tree with apps, deps, and mounts."""
    _ = isolated_registry
    space = _space(
        tmp_path,
        "name: demo\n"
        "apps:\n"
        "  api:\n"
        "    deps: [postgres]\n"
        "    service:\n"
        "      image: alpine:3.20\n"
        "  postgres:\n"
        "    service:\n"
        "      image: postgres:16\n"
        "mounts:\n"
        "  shared:\n"
        "    hosted_in: [api]\n"
        "    exec_path: /mnt/shared\n",
    )
    result = runner.invoke(app, ["-f", str(space), "graph"])
    assert result.exit_code == 0, result.stdout
    assert "demo" in result.stdout
    assert "api" in result.stdout
    assert "postgres" in result.stdout


def test_graph_works_without_bases_or_mounts(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """Spaces without ``bases:`` / ``mounts:`` still graph cleanly."""
    _ = isolated_registry
    space = _space(
        tmp_path,
        "name: tiny\napps:\n  api:\n    service:\n      image: alpine:3.20\n",
    )
    result = runner.invoke(app, ["-f", str(space), "graph"])
    assert result.exit_code == 0, result.stdout
    assert "api" in result.stdout


def test_stats_invokes_docker_stats(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cupli stats`` shells out to ``docker stats`` with workspace containers."""
    _ = isolated_registry
    space = _space(
        tmp_path,
        "name: demo\napps:\n  api:\n    service:\n      image: alpine:3.20\n",
    )

    captured: list[list[str]] = []

    def _fake_run(argv: list[str], **kwargs: object) -> object:
        _ = kwargs
        captured.append(argv)

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr("cupli.cli.diagnostics.run_command", _fake_run)

    result = runner.invoke(app, ["-f", str(space), "stats"])
    assert result.exit_code == 0, result.stdout
    assert captured, "docker stats was not invoked"
    assert captured[-1][:2] == ["docker", "stats"]
