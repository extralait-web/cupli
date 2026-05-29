"""Tests for the ``cupli exports`` subapp."""

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


def _space_with_export(tmp_path: Path) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\n"
        "apps:\n"
        "  web: {}\n"
        "exports:\n"
        "  web-nm:\n"
        "    from: web\n"
        "    exec_path: /app/node_modules\n"
        "    path: ${WEB_APP_PATH}/node_modules\n",
        encoding="utf-8",
    )
    return space_file


def test_exports_list_renders_table(runner: CliRunner, tmp_path: Path, isolated_registry: Path) -> None:
    """``cupli exports list`` shows the declared export and its status."""
    _ = isolated_registry
    space = _space_with_export(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "exports", "list"])
    assert result.exit_code == 0, result.stdout
    assert "web-nm" in result.stdout
    assert "missing" in result.stdout


def test_exports_clean_is_clean_when_nothing_materialised(
    runner: CliRunner, tmp_path: Path, isolated_registry: Path
) -> None:
    """``cupli exports clean`` succeeds even when no host copy exists."""
    _ = isolated_registry
    space = _space_with_export(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "exports", "clean"])
    assert result.exit_code == 0, result.stdout


def test_exports_sync_without_docker_reports_missing(
    runner: CliRunner, tmp_path: Path, isolated_registry: Path
) -> None:
    """Without docker, sync degrades gracefully (exit 0, status missing)."""
    _ = isolated_registry
    space = _space_with_export(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "exports", "sync"])
    assert result.exit_code == 0, result.stdout
    assert "web-nm" in result.stdout
