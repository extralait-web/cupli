"""Tests for :mod:`cupli.core.registry`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cupli.core import registry
from cupli.domain.errors import CupliError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the registry path into a per-test temporary file."""
    registry_path = tmp_path / "spaces.json"
    monkeypatch.setattr(registry, "spaces_registry_path", lambda: registry_path)
    return registry_path


def test_empty_registry_returns_empty_dict(isolated_registry: Path) -> None:
    """A missing registry file is created on first read and yields ``{}``."""
    assert registry.list_known_spaces() == {}
    assert isolated_registry.exists()


def test_add_and_list_round_trip(tmp_path: Path, isolated_registry: Path) -> None:
    """``add_space`` is round-tripped through ``list_known_spaces``."""
    _ = isolated_registry
    target = tmp_path / "demo" / "space.cupli.yaml"
    target.parent.mkdir()
    target.touch()
    registry.add_space("demo", target)
    assert registry.list_known_spaces() == {"demo": target}


def test_add_same_path_is_idempotent(tmp_path: Path, isolated_registry: Path) -> None:
    """Re-adding the same ``(name, path)`` is a no-op."""
    _ = isolated_registry
    target = tmp_path / "demo" / "space.cupli.yaml"
    target.parent.mkdir()
    target.touch()
    registry.add_space("demo", target)
    registry.add_space("demo", target)
    assert registry.list_known_spaces() == {"demo": target}


def test_add_conflicting_path_raises_e019(tmp_path: Path, isolated_registry: Path) -> None:
    """Re-adding with a different path raises ``E019``."""
    _ = isolated_registry
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.touch()
    b.touch()
    registry.add_space("demo", a)
    with pytest.raises(CupliError) as exc_info:
        registry.add_space("demo", b)
    assert exc_info.value.code == "E019"


def test_get_unknown_space_raises_e020(isolated_registry: Path) -> None:
    """``get_space_path`` raises ``E020`` for unknown names."""
    _ = isolated_registry
    with pytest.raises(CupliError) as exc_info:
        registry.get_space_path("ghost")
    assert exc_info.value.code == "E020"


def test_remove_drops_entry(tmp_path: Path, isolated_registry: Path) -> None:
    """``remove_space`` removes the named entry."""
    _ = isolated_registry
    target = tmp_path / "demo.yaml"
    target.touch()
    registry.add_space("demo", target)
    registry.remove_space("demo")
    assert registry.list_known_spaces() == {}


def test_remove_missing_raises_e020(isolated_registry: Path) -> None:
    """``remove_space`` raises ``E020`` when the name is not registered."""
    _ = isolated_registry
    with pytest.raises(CupliError) as exc_info:
        registry.remove_space("ghost")
    assert exc_info.value.code == "E020"


def test_rename_round_trip(tmp_path: Path, isolated_registry: Path) -> None:
    """``rename_space`` moves the entry under a new name."""
    _ = isolated_registry
    target = tmp_path / "demo.yaml"
    target.touch()
    registry.add_space("old", target)
    registry.rename_space("old", "new")
    assert registry.list_known_spaces() == {"new": target}


def test_rename_to_existing_raises_e019(tmp_path: Path, isolated_registry: Path) -> None:
    """``rename_space`` raises ``E019`` when the target name is taken."""
    _ = isolated_registry
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.touch()
    b.touch()
    registry.add_space("one", a)
    registry.add_space("two", b)
    with pytest.raises(CupliError) as exc_info:
        registry.rename_space("one", "two")
    assert exc_info.value.code == "E019"


def test_detect_current_space_uses_registry_prefix(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """The detector returns the registered space whose root is a prefix of cwd."""
    _ = isolated_registry
    root = tmp_path / "ws"
    nested = root / "src" / "deep"
    nested.mkdir(parents=True)
    space_file = root / "space.cupli.yaml"
    space_file.touch()
    registry.add_space("demo", space_file)
    detected = registry.detect_current_space(nested)
    assert detected.is_known is True
    assert detected.name == "demo"
    assert detected.path == space_file


def test_detect_current_space_falls_back_to_cwd_scan(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """When no registry hit, the detector scans the cwd for a space file."""
    _ = isolated_registry
    space_file = tmp_path / "my.cupli.yaml"
    space_file.touch()
    detected = registry.detect_current_space(tmp_path)
    assert detected.is_known is False
    assert detected.name is None
    assert detected.path == space_file


def test_detect_current_space_raises_e001_when_nothing_found(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """The detector raises ``E001`` when neither registry nor cwd contain a space."""
    _ = isolated_registry
    with pytest.raises(CupliError) as exc_info:
        registry.detect_current_space(tmp_path)
    assert exc_info.value.code == "E001"


def test_detect_current_space_picks_longest_matching_prefix(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """When two registered roots both prefix cwd, the deeper one wins."""
    _ = isolated_registry
    parent = tmp_path / "parent"
    nested = parent / "nested"
    nested.mkdir(parents=True)
    outer_file = parent / "outer.cupli.yaml"
    inner_file = nested / "inner.cupli.yaml"
    outer_file.touch()
    inner_file.touch()
    registry.add_space("outer", outer_file)
    registry.add_space("inner", inner_file)
    detected = registry.detect_current_space(nested)
    assert detected.name == "inner"


# --- active-space slot -----------------------------------------------------


def test_active_defaults_to_none(isolated_registry: Path) -> None:
    """A fresh registry has no active selection."""
    _ = isolated_registry
    assert registry.get_active_space() is None


def test_set_and_get_active(tmp_path: Path, isolated_registry: Path) -> None:
    """``set_active_space`` round-trips through ``get_active_space``."""
    _ = isolated_registry
    target = tmp_path / "a.yaml"
    target.touch()
    registry.add_space("alpha", target)
    registry.set_active_space("alpha")
    assert registry.get_active_space() == "alpha"


def test_set_active_unknown_raises_e020(isolated_registry: Path) -> None:
    """Selecting a non-registered name surfaces ``E020``."""
    _ = isolated_registry
    with pytest.raises(CupliError) as exc_info:
        registry.set_active_space("ghost")
    assert exc_info.value.code == "E020"


def test_clear_active(tmp_path: Path, isolated_registry: Path) -> None:
    """``set_active_space(None)`` removes the selection."""
    _ = isolated_registry
    target = tmp_path / "a.yaml"
    target.touch()
    registry.add_space("alpha", target)
    registry.set_active_space("alpha")
    registry.set_active_space(None)
    assert registry.get_active_space() is None


def test_remove_clears_active_when_it_matches(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """Dropping the active entry clears the slot."""
    _ = isolated_registry
    target = tmp_path / "a.yaml"
    target.touch()
    registry.add_space("alpha", target)
    registry.set_active_space("alpha")
    registry.remove_space("alpha")
    assert registry.get_active_space() is None


def test_rename_rewires_active_when_it_matches(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """Renaming the active entry preserves it under the new name."""
    _ = isolated_registry
    target = tmp_path / "a.yaml"
    target.touch()
    registry.add_space("alpha", target)
    registry.set_active_space("alpha")
    registry.rename_space("alpha", "beta")
    assert registry.get_active_space() == "beta"


def test_detect_falls_back_to_active(tmp_path: Path, isolated_registry: Path) -> None:
    """When cwd is unrelated to any registered space, ``active`` wins."""
    _ = isolated_registry
    target = tmp_path / "ws" / "space.cupli.yaml"
    target.parent.mkdir()
    target.touch()
    registry.add_space("alpha", target)
    registry.set_active_space("alpha")
    detected = registry.detect_current_space(tmp_path / "elsewhere")
    assert detected.name == "alpha"
    assert detected.is_known is True


def test_malformed_registry_falls_back_to_empty(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """A non-versioned registry payload is treated as empty (no migration)."""
    _ = tmp_path
    isolated_registry.write_text('{"alpha": "/foo"}', encoding="utf-8")
    assert registry.list_known_spaces() == {}
    assert registry.get_active_space() is None
