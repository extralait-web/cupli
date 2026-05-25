"""Tests for the auto-registration behaviour of :func:`load_space`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cupli.core import registry
from cupli.core.loader import load_space

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the spaces registry to a per-test JSON file."""
    registry_path = tmp_path / "spaces.json"
    monkeypatch.setattr(registry, "spaces_registry_path", lambda: registry_path)
    return registry_path


def _write_space(target: Path, body: str = "name: auto\napps:\n  api: {}\n") -> Path:
    target.write_text(body, encoding="utf-8")
    return target


def test_load_space_auto_registers_new_space(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """A first-time load adds the space to the registry under its declared name."""
    _ = isolated_registry
    space_file = _write_space(tmp_path / "space.cupli.yaml")
    assert registry.list_known_spaces() == {}
    load_space(space_file)
    assert registry.list_known_spaces() == {"auto": space_file.resolve()}


def test_load_space_does_not_overwrite_existing_name(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """An existing registry entry under the same name is left untouched."""
    _ = isolated_registry
    other_file = tmp_path / "other.cupli.yaml"
    _write_space(other_file)
    registry.add_space("auto", other_file)

    fresh_dir = tmp_path / "fresh"
    fresh_dir.mkdir()
    fresh_file = _write_space(fresh_dir / "space.cupli.yaml")
    load_space(fresh_file)
    # The original entry survives; the new load does not overwrite.
    assert registry.list_known_spaces()["auto"] == other_file


def test_load_space_auto_register_can_be_disabled(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``auto_register=False`` keeps the registry empty."""
    _ = isolated_registry
    space_file = _write_space(tmp_path / "space.cupli.yaml")
    load_space(space_file, auto_register=False)
    assert registry.list_known_spaces() == {}
