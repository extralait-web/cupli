"""Tests for the typer shell-completion callbacks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cupli.cli import _completion
from cupli.cli._completion import (
    complete_app_names,
    complete_branch_map,
    complete_error_codes,
    complete_hook_scope,
    complete_hook_targets,
    complete_mount_names,
    complete_service_names,
    complete_shortcut_names,
    complete_space_names,
    complete_tag_names,
)
from cupli.core import cache, registry
from cupli.core.loader import load_space

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the registry file to a per-test path."""
    registry_path = tmp_path / "spaces.json"
    monkeypatch.setattr(registry, "spaces_registry_path", lambda: registry_path)
    return registry_path


def _space(tmp_path: Path) -> Path:
    space = tmp_path / "space.cupli.yaml"
    space.write_text(
        "name: demo\n"
        "apps:\n"
        "  api:\n"
        "    tags: [backend]\n"
        "    service:\n"
        "      image: alpine:3.20\n"
        "  worker:\n"
        "    tags: [backend, async]\n"
        "    service:\n"
        "      image: alpine:3.20\n"
        "mounts:\n"
        "  shared:\n"
        "    hosted_in: [api]\n"
        "    exec_path: /mnt/shared\n"
        "commands:\n"
        "  test:\n"
        "    container: api\n"
        "    run: pytest\n",
        encoding="utf-8",
    )
    return space


@pytest.fixture()
def _stub_resolved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_registry: Path) -> None:
    """Pretend ``_resolved_space_quiet`` returns a real loaded space."""
    _ = isolated_registry
    resolved = load_space(_space(tmp_path))
    monkeypatch.setattr(_completion, "_resolved_space_quiet", lambda: resolved)


def test_complete_hook_scope_filters_prefix() -> None:
    """Fixed hook-scope completions filter by ``startswith``."""
    assert complete_hook_scope("a") == ["all", "apps"]


def test_complete_hook_scope_empty_prefix_returns_all() -> None:
    """Empty prefix returns the canonical full list."""
    assert complete_hook_scope("") == ["all", "apps", "bases", "mounts"]


def test_complete_error_codes_uppercases_input() -> None:
    """Lowercase ``e02`` still matches the uppercase error codes."""
    candidates = complete_error_codes("e02")
    assert candidates
    assert all(code.startswith("E02") for code in candidates)


def test_complete_space_names_returns_registered_names(
    isolated_registry: Path,
    tmp_path: Path,
) -> None:
    """Registered spaces are returned in sorted order."""
    _ = isolated_registry
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text("name: demo\napps: {}\n", encoding="utf-8")
    registry.add_space("zeta", space_file)
    registry.add_space("alpha", space_file)
    assert complete_space_names("") == ["alpha", "zeta"]
    assert complete_space_names("a") == ["alpha"]


def test_complete_space_names_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registry failures are caught and surface an empty list."""
    from cupli.domain.errors import CupliError

    def _boom() -> dict[str, object]:
        raise CupliError("E001", path="/tmp")

    monkeypatch.setattr(registry, "list_known_spaces", _boom)
    assert complete_space_names("") == []


def test_complete_service_names_returns_apps(_stub_resolved: None) -> None:
    """Service completions include the primary service name for each app."""
    candidates = complete_service_names("")
    assert "api" in candidates
    assert "worker" in candidates


def test_complete_app_names_filters_by_prefix(_stub_resolved: None) -> None:
    """App names are filtered by ``startswith``."""
    assert complete_app_names("w") == ["worker"]


def test_complete_mount_names_returns_declared(_stub_resolved: None) -> None:
    """Declared mount keys appear in the completion list."""
    assert complete_mount_names("") == ["shared"]


def test_complete_tag_names_aggregates_app_tags(_stub_resolved: None) -> None:
    """Tags from every app are flattened, deduplicated, and sorted."""
    assert complete_tag_names("") == ["async", "backend"]


def test_complete_hook_targets_lists_apps_and_mounts(_stub_resolved: None) -> None:
    """Hook-target completions cover apps, bases, and mounts."""
    candidates = complete_hook_targets("")
    assert {"api", "worker", "shared"}.issubset(candidates)


def test_complete_branch_map_appends_equals(_stub_resolved: None) -> None:
    """Branch-map completions append ``=`` so the shell pauses for the branch."""
    assert "api=" in complete_branch_map("")


def test_complete_branch_map_skips_when_equals_in_input(_stub_resolved: None) -> None:
    """A token that already has ``=`` short-circuits the lookup."""
    assert complete_branch_map("api=") == []


def test_complete_service_names_returns_empty_when_no_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the quiet loader gives up, the callback returns an empty list."""
    monkeypatch.setattr(_completion, "_resolved_space_quiet", lambda: None)
    assert complete_service_names("") == []


def test_resolved_space_quiet_returns_none_when_detection_fails(
    isolated_registry: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_resolved_space_quiet`` swallows ``detect_current_space`` failures."""
    _ = isolated_registry
    monkeypatch.chdir(tmp_path)
    # No space file in cwd → detect_current_space raises E001 → callback returns None.
    assert _completion._resolved_space_quiet() is None


def test_complete_shortcut_names_uses_cache_when_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """A warm cache short-circuits the loader path."""
    _ = isolated_registry
    space = _space(tmp_path)
    monkeypatch.chdir(tmp_path)
    registry.add_space("demo", space)

    class _FakeCache:
        commands = {"test": {"run": "pytest"}}

    monkeypatch.setattr(cache, "read_commands", lambda _path: _FakeCache())
    assert complete_shortcut_names("t") == ["test"]


def test_complete_shortcut_names_falls_back_to_loader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """On a cache miss the loader path returns the declared commands."""
    _ = isolated_registry
    space = _space(tmp_path)
    monkeypatch.chdir(tmp_path)
    registry.add_space("demo", space)
    monkeypatch.setattr(cache, "read_commands", lambda _path: None)
    assert complete_shortcut_names("") == ["test"]
