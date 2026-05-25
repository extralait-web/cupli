"""Tests for the ``cupli mounts`` subapp."""

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
    """Fresh CliRunner per test."""
    return CliRunner()


def _space_with_mount(tmp_path: Path) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        ("name: demo\napps:\n  api: {}\nmounts:\n  sdk:\n    hosted_in: [api]\n    exec_path: /opt/sdk\n"),
        encoding="utf-8",
    )
    return space_file


def test_mounts_list_renders_table(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli mounts list`` prints the declared mounts."""
    _ = isolated_registry
    space = _space_with_mount(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "mounts", "list"])
    assert result.exit_code == 0, result.stdout
    assert "sdk" in result.stdout
    assert "/opt/sdk" in result.stdout


def test_mounts_detach_then_attach(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``detach`` then ``attach`` round-trips with success messages."""
    _ = isolated_registry
    space = _space_with_mount(tmp_path)
    detach_result = runner.invoke(app, ["-f", str(space), "mounts", "detach", "sdk", "--no-restart"])
    assert detach_result.exit_code == 0
    assert "detached" in detach_result.stdout
    attach_result = runner.invoke(app, ["-f", str(space), "mounts", "attach", "sdk", "--no-restart"])
    assert attach_result.exit_code == 0
    assert "attached" in attach_result.stdout


def test_mounts_attach_unknown_exits_one(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """Attaching an unknown mount surfaces ``E020`` and exits with code 1."""
    _ = isolated_registry
    space = _space_with_mount(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "mounts", "attach", "ghost", "--no-restart"])
    assert result.exit_code == 1
    assert "E020" in result.stdout
