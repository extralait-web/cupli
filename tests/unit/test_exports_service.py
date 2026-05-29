"""Tests for :mod:`cupli.services.exports_service`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cupli.domain.errors import CupliError
from cupli.services import exports_service as es

if TYPE_CHECKING:
    from pathlib import Path

_CONFIG = {
    "services": {
        "web": {
            "image": "demo-web:latest",
            "volumes": [{"type": "volume", "source": "nm", "target": "/app/node_modules"}],
        }
    },
    "volumes": {"nm": {"name": "demo_nm"}},
}
"""A synthetic ``docker compose config`` doc with a named volume at node_modules."""


def _space(tmp_path: Path, *, strategy: str = "sync", gitignore: bool = True) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\n"
        "apps:\n"
        "  web: {}\n"
        "exports:\n"
        "  web-nm:\n"
        "    from: web\n"
        "    exec_path: /app/node_modules\n"
        "    path: ${WEB_APP_PATH}/node_modules\n"
        f"    strategy: {strategy}\n"
        f"    gitignore: {'true' if gitignore else 'false'}\n",
        encoding="utf-8",
    )
    return space_file


def _load(tmp_path: Path, **kw):
    from cupli.core.loader import load_space

    return load_space(_space(tmp_path, **kw), auto_register=False, auto_cache=False)


# --- pure config lookups ---------------------------------------------------


def test_volume_for_exec_path_resolves_project_qualified_name() -> None:
    """The declared volume source resolves to its real (project-qualified) name."""
    assert es.volume_for_exec_path(_CONFIG, {"web"}, "/app/node_modules") == "demo_nm"


def test_volume_for_exec_path_none_when_absent() -> None:
    """No named volume at the path yields ``None``."""
    assert es.volume_for_exec_path(_CONFIG, {"web"}, "/nowhere") is None


def test_service_image_returns_first_match() -> None:
    """``service_image`` returns the resolved image of a matching service."""
    assert es.service_image(_CONFIG, {"web"}) == "demo-web:latest"


# --- listing / status ------------------------------------------------------


def test_list_exports_missing_before_sync(tmp_path: Path) -> None:
    """An unmaterialised export reads as ``missing``."""
    resolved = _load(tmp_path)
    rows = es.list_exports(resolved)
    assert len(rows) == 1
    assert rows[0].name == "web-nm"
    assert rows[0].status == "missing"
    assert rows[0].strategy == "sync"


def test_mark_stale_then_synced_transition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A build marks an export stale; a sync clears it to ``synced``."""
    resolved = _load(tmp_path)

    def fake_sync(volume: str, image: str, host_path) -> None:
        (host_path / "left-pad").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(es, "_docker_sync", fake_sync)
    es.mark_stale(resolved, "web")
    assert es.list_exports(resolved)[0].status == "stale"
    rows = es.sync_exports(resolved, config=_CONFIG)
    assert rows[0].status == "synced"
    assert es.list_exports(resolved)[0].status == "synced"


def test_sync_without_docker_reports_missing(tmp_path: Path) -> None:
    """With no resolvable volume/image, sync degrades to ``missing`` (no crash)."""
    resolved = _load(tmp_path)
    rows = es.sync_exports(resolved, config=None)
    assert rows[0].status == "missing"


# --- conflict / clean ------------------------------------------------------


def test_sync_conflict_on_foreign_dir_raises_e032(tmp_path: Path) -> None:
    """A pre-existing non-empty host dir cupli did not create raises ``E032``."""
    resolved = _load(tmp_path)
    host = resolved.exports["web-nm"].path
    host.mkdir(parents=True)
    (host / "vendored").write_text("mine", encoding="utf-8")
    with pytest.raises(CupliError) as exc:
        es.sync_exports(resolved, config=_CONFIG)
    assert exc.value.code == "E032"


def test_clean_removes_sync_host_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``clean_exports`` deletes a synced host copy and forgets its state."""
    resolved = _load(tmp_path)
    monkeypatch.setattr(es, "_docker_sync", lambda v, i, p: (p / "x").mkdir(exist_ok=True))
    es.sync_exports(resolved, config=_CONFIG)
    host = resolved.exports["web-nm"].path
    assert host.exists()
    rows = es.clean_exports(resolved)
    assert rows[0].status == "missing"
    assert not host.exists()


# --- gitignore -------------------------------------------------------------


def test_gitignore_added_idempotently(tmp_path: Path) -> None:
    """``ensure_gitignore`` adds an anchored entry once under a cupli section."""
    space_dir = tmp_path
    target = tmp_path / "src/apps/web/node_modules"
    es.ensure_gitignore(space_dir, [target])
    es.ensure_gitignore(space_dir, [target])
    content = (space_dir / ".gitignore").read_text(encoding="utf-8")
    assert "# cupli exports" in content
    assert content.count("/src/apps/web/node_modules") == 1


def test_sync_writes_gitignore_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``gitignore: true`` export adds its host path to the root .gitignore."""
    resolved = _load(tmp_path)
    monkeypatch.setattr(es, "_docker_sync", lambda v, i, p: (p / "x").mkdir(exist_ok=True))
    es.sync_exports(resolved, config=_CONFIG)
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/src/apps/web/node_modules" in gitignore
