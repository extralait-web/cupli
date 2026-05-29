"""Tests for the ``cupli mounts`` subapp."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cupli.cli.root import app
from cupli.core import registry


def _symlinks_supported() -> bool:
    """True when the platform/user can create symlinks (false on locked-down Windows)."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            (Path(tmp) / "probe").symlink_to(tmp)
        except OSError:
            return False
        return True


needs_symlinks = pytest.mark.skipif(not _symlinks_supported(), reason="platform cannot create symlinks")


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


def _space_with_bridge(tmp_path: Path) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\n"
        "apps:\n"
        "  web: {}\n"
        "mounts:\n"
        "  ui:\n"
        "    hosted_in: [web]\n"
        "    path: ${MOUNTS_PATH}/ui-lib\n"
        "    exec_path: /app/packages/ui\n"
        "    host_bridge:\n"
        "      link: ${WEB_APP_PATH}/packages/ui\n",
        encoding="utf-8",
    )
    return space_file


@needs_symlinks
def test_mounts_bridge_then_unbridge(runner: CliRunner, tmp_path: Path, isolated_registry: Path) -> None:
    """``mounts bridge`` creates the symlink; ``unbridge`` removes it."""
    _ = isolated_registry
    space = _space_with_bridge(tmp_path)
    link = tmp_path / "src/apps/web/packages/ui"
    bridge = runner.invoke(app, ["-f", str(space), "mounts", "bridge"])
    assert bridge.exit_code == 0, bridge.stdout
    assert link.is_symlink()
    unbridge = runner.invoke(app, ["-f", str(space), "mounts", "unbridge"])
    assert unbridge.exit_code == 0, unbridge.stdout
    assert not link.exists()


def test_mounts_list_shows_bridge_column(runner: CliRunner, tmp_path: Path, isolated_registry: Path) -> None:
    """``mounts list`` reports the bridge status (``pending`` before creation)."""
    _ = isolated_registry
    space = _space_with_bridge(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "mounts", "list"])
    assert result.exit_code == 0, result.stdout
    assert "bridge" in result.stdout
