"""Tests for :mod:`cupli.core.cache`."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from cupli.core.cache import CachedCommands, clear_cache, read_commands, write_commands
from cupli.domain.models import CommandShortcut

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``$XDG_CACHE_HOME`` so cache writes land in ``tmp_path``."""
    root = tmp_path / "xdg-cache"
    root.mkdir()
    monkeypatch.setenv("XDG_CACHE_HOME", str(root))
    monkeypatch.delenv("CUPLI_CACHE_FILE", raising=False)
    return root / "cupli"


def _make_space_file(tmp_path: Path) -> Path:
    space = tmp_path / "space.cupli.yaml"
    space.write_text("name: demo\napps: {}\n", encoding="utf-8")
    return space


def _make_shortcuts() -> dict[str, CommandShortcut]:
    return {
        "test": CommandShortcut(
            container="api",
            run="pytest",
            workdir=None,
            help="Run tests",
            top_level=True,
        ),
    }


def test_read_commands_returns_none_for_missing_source(tmp_path: Path, isolated_cache: Path) -> None:
    """A missing source file produces an empty signature and ``None``."""
    _ = isolated_cache
    missing = tmp_path / "absent.cupli.yaml"
    assert read_commands(missing) is None


def test_read_commands_returns_none_when_cache_root_empty(tmp_path: Path, isolated_cache: Path) -> None:
    """A fresh cache root has no entries to scan."""
    _ = isolated_cache
    space = _make_space_file(tmp_path)
    assert read_commands(space) is None


def test_write_then_read_roundtrips_payload(tmp_path: Path, isolated_cache: Path) -> None:
    """``write_commands`` produces a hit that ``read_commands`` recognises."""
    space = _make_space_file(tmp_path)
    write_commands(space, "demo", _make_shortcuts())
    cached = read_commands(space)
    assert isinstance(cached, CachedCommands)
    assert cached.space_name == "demo"
    assert cached.commands["test"]["run"] == "pytest"
    assert isinstance(isolated_cache, type(isolated_cache))


def test_read_commands_skips_invalid_blobs(tmp_path: Path, isolated_cache: Path) -> None:
    """A cache file that is not valid JSON is silently ignored."""
    space = _make_space_file(tmp_path)
    write_commands(space, "demo", _make_shortcuts())
    cache_file = isolated_cache / "demo" / "cache.json"
    cache_file.write_text("not json", encoding="utf-8")
    assert read_commands(space) is None


def test_read_commands_skips_stale_signature(tmp_path: Path, isolated_cache: Path) -> None:
    """A stored signature that no longer matches the source is treated as a miss."""
    _ = isolated_cache
    space = _make_space_file(tmp_path)
    write_commands(space, "demo", _make_shortcuts())
    # Mutate the source so size+sha drift; mtime advances on rewrite as well.
    space.write_text("name: demo\napps:\n  api: {}\n", encoding="utf-8")
    assert read_commands(space) is None


def test_read_commands_skips_other_sources(tmp_path: Path, isolated_cache: Path) -> None:
    """Cache rows pointing at a different ``space_file`` are ignored."""
    _ = isolated_cache
    primary = _make_space_file(tmp_path)
    other = tmp_path / "other.cupli.yaml"
    other.write_text("name: other\napps: {}\n", encoding="utf-8")
    write_commands(other, "other", _make_shortcuts())
    assert read_commands(primary) is None


def test_read_commands_rejects_malformed_commands_dict(tmp_path: Path, isolated_cache: Path) -> None:
    """A blob whose ``commands`` is not a dict resolves to ``None``."""
    space = _make_space_file(tmp_path)
    write_commands(space, "demo", _make_shortcuts())
    cache_file = isolated_cache / "demo" / "cache.json"
    blob = json.loads(cache_file.read_text(encoding="utf-8"))
    blob["commands"] = ["broken"]
    cache_file.write_text(json.dumps(blob), encoding="utf-8")
    assert read_commands(space) is None


def test_write_commands_noop_for_missing_source(tmp_path: Path, isolated_cache: Path) -> None:
    """A non-existent source skips the write rather than crashing."""
    _ = isolated_cache
    write_commands(tmp_path / "missing.yaml", "demo", _make_shortcuts())
    # Cache directory may exist (from _cache_root) but the per-space entry must not.
    assert not (isolated_cache / "demo").exists()


def test_clear_cache_for_named_space_only_drops_that_subdir(
    tmp_path: Path,
    isolated_cache: Path,
) -> None:
    """``clear_cache(name)`` removes one subdir; other spaces survive."""
    a = _make_space_file(tmp_path / "a") if False else _make_space_file(tmp_path)
    b = tmp_path / "b.cupli.yaml"
    b.write_text("name: b\napps: {}\n", encoding="utf-8")
    write_commands(a, "demo", _make_shortcuts())
    write_commands(b, "other", _make_shortcuts())
    clear_cache("demo")
    assert not (isolated_cache / "demo").exists()
    assert (isolated_cache / "other").exists()


def test_clear_cache_drops_entire_root_when_name_is_none(
    tmp_path: Path,
    isolated_cache: Path,
) -> None:
    """``clear_cache(None)`` purges the whole cupli cache root."""
    space = _make_space_file(tmp_path)
    write_commands(space, "demo", _make_shortcuts())
    assert isolated_cache.exists()
    clear_cache(None)
    assert not isolated_cache.exists()
