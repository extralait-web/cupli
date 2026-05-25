"""Tests for ``cupli init`` / ``cupli workspace`` / ``cupli space``."""

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
    """Redirect the registry to a per-test JSON file."""
    registry_path = tmp_path / "spaces.json"
    monkeypatch.setattr(registry, "spaces_registry_path", lambda: registry_path)
    return registry_path


@pytest.fixture()
def runner() -> CliRunner:
    """Provide a fresh :class:`CliRunner`."""
    return CliRunner()


def test_init_scaffolds_space(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli init -n demo -p <dir>`` creates the space file + state dir."""
    _ = isolated_registry
    target = tmp_path / "demo"
    result = runner.invoke(app, ["init", "-n", "demo", "-p", str(target)])
    assert result.exit_code == 0, result.stdout
    assert (target / "space.cupli.yaml").exists()
    assert (target / ".locals").is_dir()
    assert not (target / "src" / "apps").exists()
    assert not (target / "src" / "bases").exists()
    assert not (target / "src" / "mounts").exists()


def test_init_derives_name_from_target_dir(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli init -p <dir>`` (no --name) uses ``<dir>``'s basename."""
    _ = isolated_registry
    target = tmp_path / "my-project"
    result = runner.invoke(app, ["init", "-p", str(target)])
    assert result.exit_code == 0, result.stdout
    body = (target / "space.cupli.yaml").read_text(encoding="utf-8")
    assert "name: my-project" in body


def test_init_sanitises_invalid_dir_name(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """Spaces and other invalid chars in the directory name become hyphens."""
    _ = isolated_registry
    target = tmp_path / "My Cool Project"
    result = runner.invoke(app, ["init", "-p", str(target)])
    assert result.exit_code == 0, result.stdout
    body = (target / "space.cupli.yaml").read_text(encoding="utf-8")
    assert "name: My-Cool-Project" in body


def test_init_fails_friendly_when_dir_name_starts_with_digit(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """A name that does not match NAME_PATTERN raises E009 with a hint."""
    _ = isolated_registry
    target = tmp_path / "123"
    result = runner.invoke(app, ["init", "-p", str(target)])
    assert result.exit_code == 1
    assert "E009" in result.stdout


def test_init_with_existing_file_registers_under_declared_name(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """When ``space.cupli.yaml`` exists, ``init`` honours its declared name."""
    _ = isolated_registry
    target = tmp_path / "wrong-cwd-name"
    target.mkdir()
    (target / "space.cupli.yaml").write_text(
        "name: example\napps:\n  api: {}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["init", "-p", str(target)])
    assert result.exit_code == 0, result.stdout
    assert "example" in result.stdout
    assert registry.list_known_spaces() == {"example": target / "space.cupli.yaml"}


def test_init_with_existing_file_is_idempotent(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """A second ``init`` run against the same existing file is a no-op."""
    _ = isolated_registry
    target = tmp_path / "ws"
    target.mkdir()
    (target / "space.cupli.yaml").write_text(
        "name: ws\napps:\n  api: {}\n",
        encoding="utf-8",
    )
    first = runner.invoke(app, ["init", "-p", str(target)])
    second = runner.invoke(app, ["init", "-p", str(target)])
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "already registered" in second.stdout


def test_init_existing_file_with_conflicting_registration_raises_e019(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """If the declared name already points elsewhere, E019 surfaces clearly."""
    _ = isolated_registry
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_file = other_dir / "space.cupli.yaml"
    other_file.write_text("name: example\napps:\n  api: {}\n", encoding="utf-8")
    registry.add_space("example", other_file)

    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "space.cupli.yaml").write_text(
        "name: example\napps:\n  api: {}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["init", "-p", str(target)])
    assert result.exit_code == 1
    assert "E019" in result.stdout


def test_workspace_add_and_list(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``workspace add`` then ``workspace list`` round-trip."""
    _ = isolated_registry
    space_file = tmp_path / "ws.cupli.yaml"
    space_file.touch()
    add_result = runner.invoke(app, ["workspace", "add", "-n", "demo", "-f", str(space_file)])
    assert add_result.exit_code == 0
    list_result = runner.invoke(app, ["workspace", "list"])
    assert list_result.exit_code == 0
    assert "demo" in list_result.stdout


def test_workspace_select_known(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``workspace select`` succeeds for a registered name."""
    _ = isolated_registry
    space_file = tmp_path / "ws.cupli.yaml"
    space_file.touch()
    registry.add_space("demo", space_file)
    result = runner.invoke(app, ["workspace", "select", "demo"])
    assert result.exit_code == 0


def test_workspace_select_unknown(
    runner: CliRunner,
    isolated_registry: Path,
) -> None:
    """``workspace select`` on a missing name exits with E020."""
    _ = isolated_registry
    result = runner.invoke(app, ["workspace", "select", "ghost"])
    assert result.exit_code == 1
    assert "E020" in result.stdout


def test_workspace_unselect_clears_active(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``workspace unselect`` clears the sticky active selection."""
    _ = isolated_registry
    space_file = tmp_path / "ws.cupli.yaml"
    space_file.touch()
    registry.add_space("demo", space_file)
    registry.set_active_space("demo")
    assert registry.get_active_space() == "demo"
    result = runner.invoke(app, ["workspace", "unselect"])
    assert result.exit_code == 0
    assert "unselected demo" in result.stdout
    assert registry.get_active_space() is None


def test_workspace_unselect_noop_when_unset(
    runner: CliRunner,
    isolated_registry: Path,
) -> None:
    """``workspace unselect`` is a no-op when no active selection exists."""
    _ = isolated_registry
    assert registry.get_active_space() is None
    result = runner.invoke(app, ["workspace", "unselect"])
    assert result.exit_code == 0
    assert "no active workspace" in result.stdout


def test_workspace_remove(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``workspace remove`` drops the entry."""
    _ = isolated_registry
    space_file = tmp_path / "ws.cupli.yaml"
    space_file.touch()
    registry.add_space("demo", space_file)
    result = runner.invoke(app, ["workspace", "remove", "demo"])
    assert result.exit_code == 0
    assert registry.list_known_spaces() == {}


def test_space_doctor_runs(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli space doctor -f <path>`` returns 0 for a clean space."""
    _ = isolated_registry
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text("name: clean\napps:\n  api: {}\n", encoding="utf-8")
    (tmp_path / "src" / "apps" / "api").mkdir(parents=True)
    result = runner.invoke(app, ["-f", str(space_file), "space", "doctor"])
    assert result.exit_code == 0, result.stdout


def test_space_doctor_strict_fails_on_warnings(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``--strict`` turns warnings into non-zero exit."""
    _ = isolated_registry
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: warns\napps:\n  api:\n    repo: git@github.com:o/r.git\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["-f", str(space_file), "space", "doctor", "--strict"])
    assert result.exit_code == 1
