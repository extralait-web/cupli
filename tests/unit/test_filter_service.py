"""Tests for :mod:`cupli.services.filter_service`."""

from __future__ import annotations

from cupli.core.loader import load_space
from cupli.domain.enums import DepMode
from cupli.services.filter_service import closure


def _write(target, body: str):
    target.write_text(body, encoding="utf-8")
    return target


def test_closure_returns_all_apps_by_default(tmp_path) -> None:
    """An empty filter returns every declared app, dep-ordered."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        "name: t\napps:\n  a: {}\n  b:\n    deps:\n      a: [default]\n",
    )
    resolved = load_space(space_file)
    assert closure(resolved) == ["a", "b"]


def test_closure_orders_deps_before_dependants(tmp_path) -> None:
    """Dependencies precede their dependants in the returned order."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        ("name: t\napps:\n  api:\n    deps:\n      db: [default]\n  db: {}\n"),
    )
    resolved = load_space(space_file)
    out = closure(resolved)
    assert out.index("db") < out.index("api")


def test_closure_explicit_seed_includes_deps(tmp_path) -> None:
    """An explicit seed pulls its transitive deps into the closure."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        ("name: t\napps:\n  api:\n    deps:\n      db: [default]\n  db: {}\n  unrelated: {}\n"),
    )
    resolved = load_space(space_file)
    assert set(closure(resolved, names=["api"])) == {"api", "db"}


def test_closure_tag_filter(tmp_path) -> None:
    """Tags seed the closure as a union with explicit names."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        ("name: t\napps:\n  api:\n    tags: [backend]\n  worker:\n    tags: [backend]\n  web:\n    tags: [frontend]\n"),
    )
    resolved = load_space(space_file)
    assert set(closure(resolved, tags=["backend"])) == {"api", "worker"}


def test_closure_mode_filters_deps(tmp_path) -> None:
    """Edges whose mode list excludes the requested mode are skipped."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        ("name: t\napps:\n  api:\n    deps:\n      db: [hook]\n  db: {}\n"),
    )
    resolved = load_space(space_file)
    out = closure(resolved, names=["api"], mode=DepMode.DEFAULT)
    assert out == ["api"]


def test_closure_excludes_disabled_apps(tmp_path) -> None:
    """``mode=disabled`` apps disappear from the closure unless included explicitly."""
    space_file = _write(
        tmp_path / "space.cupli.yaml",
        ("name: t\napps:\n  api: {}\n  legacy:\n    mode: disabled\n"),
    )
    resolved = load_space(space_file)
    out = closure(resolved)
    assert out == ["api"]
    out_inclusive = closure(resolved, include_disabled=True)
    assert "legacy" in out_inclusive
