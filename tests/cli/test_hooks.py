"""Tests for ``cupli hooks install`` / ``cupli hooks remove``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cupli.cli.root import app
from cupli.core import registry
from cupli.domain.consts import HOOK_MARKER

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


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    """Build a tiny workspace with one git-backed app and a hooks dir."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text("name: demo\napps:\n  api: {}\n", encoding="utf-8")
    (tmp_path / "src" / "apps" / "api").mkdir(parents=True)
    (tmp_path / "src" / "apps" / "api" / ".git").mkdir()

    hooks_dir = tmp_path / "hooks"
    (hooks_dir / "pre-commit").mkdir(parents=True)
    (hooks_dir / "pre-commit" / "01-lint.sh").write_text("#!/bin/bash\nruff check .\n")
    return space_file, hooks_dir


def test_hooks_install_writes_shims(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli hooks install`` writes shims with the cupli marker."""
    _ = isolated_registry
    space_file, hooks_dir = _scaffold(tmp_path)
    result = runner.invoke(app, ["-f", str(space_file), "hooks", "install", str(hooks_dir)])
    assert result.exit_code == 0, result.stdout
    shim = tmp_path / "src" / "apps" / "api" / ".git" / "hooks" / "pre-commit"
    assert shim.exists()
    assert HOOK_MARKER in shim.read_text()


def test_hooks_remove_removes_only_cupli_owned(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli hooks remove`` removes only marker-tagged shims."""
    _ = isolated_registry
    space_file, hooks_dir = _scaffold(tmp_path)
    runner.invoke(app, ["-f", str(space_file), "hooks", "install", str(hooks_dir)])
    shim = tmp_path / "src" / "apps" / "api" / ".git" / "hooks" / "pre-commit"
    assert shim.exists()
    result = runner.invoke(app, ["-f", str(space_file), "hooks", "remove"])
    assert result.exit_code == 0
    assert not shim.exists()
