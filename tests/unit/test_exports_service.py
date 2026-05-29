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

    def fake_sync(volume: str, image: str, host_path) -> bool:
        (host_path / "left-pad").mkdir(parents=True, exist_ok=True)
        return True

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


def test_sync_status_reflects_empty_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A copy that produced no content reports ``missing``, not ``synced`` (Bug 1)."""
    resolved = _load(tmp_path)
    # Volume + image resolve, but the copy materialises nothing on the host.
    monkeypatch.setattr(es, "_docker_sync", lambda v, i, p: True)
    rows = es.sync_exports(resolved, config=_CONFIG)
    assert rows[0].status == "missing"
    assert es.list_exports(resolved)[0].status == "missing"


def test_materialise_copies_and_chowns_as_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The sync helper runs copy + chown as root in-container, never host-side (Bug 1)."""
    captured: dict[str, list[str]] = {}

    class _Done:
        returncode = 0

    def _fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return _Done()

    monkeypatch.setattr(es, "run_command", _fake_run)
    monkeypatch.setattr(es, "_owner_str", lambda: "1000:1000")
    es._docker_sync("demo_nm", "demo-web:latest", tmp_path / "dst")
    argv = captured["argv"]
    script = argv[-1]
    assert "--user" not in argv  # copy runs as root so it can read root-owned source
    assert "demo_nm:/src:ro" in argv
    assert "cp -a /src/. /dst/" in script
    assert "chown -R 1000:1000 /dst" in script  # chown happens in-container, not host-side
    assert "find /dst -mindepth 1 -delete" in script  # idempotent refresh


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
    monkeypatch.setattr(es, "_docker_sync", lambda v, i, p: bool((p / "x").mkdir(exist_ok=True)) or True)
    es.sync_exports(resolved, config=_CONFIG)
    host = resolved.exports["web-nm"].path
    assert host.exists()
    rows = es.clean_exports(resolved)
    assert rows[0].status == "removed"
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
    monkeypatch.setattr(es, "_docker_sync", lambda v, i, p: bool((p / "x").mkdir(exist_ok=True)) or True)
    es.sync_exports(resolved, config=_CONFIG)
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/src/apps/web/node_modules" in gitignore


def test_remove_from_gitignore_prunes_entry_and_empty_section(tmp_path: Path) -> None:
    """``remove_from_gitignore`` drops the entry and an emptied cupli section (Bug 6)."""
    target = tmp_path / "src/apps/web/node_modules"
    (tmp_path / ".gitignore").write_text("node\n*.log\n", encoding="utf-8")
    es.ensure_gitignore(tmp_path, [target])
    es.remove_from_gitignore(tmp_path, [target])
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "/src/apps/web/node_modules" not in content
    assert "# cupli exports" not in content  # section pruned once empty
    assert "node" in content and "*.log" in content  # user lines preserved


def test_clean_prunes_gitignore_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``clean_exports`` removes the export's .gitignore entry (Bug 6)."""
    resolved = _load(tmp_path)
    monkeypatch.setattr(es, "_docker_sync", lambda v, i, p: bool((p / "x").mkdir(exist_ok=True)) or True)
    es.sync_exports(resolved, config=_CONFIG)
    assert "/src/apps/web/node_modules" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    es.clean_exports(resolved)
    assert "/src/apps/web/node_modules" not in (tmp_path / ".gitignore").read_text(encoding="utf-8")


# --- .venv editable handling (Bug 4) ---------------------------------------


def _venv_space(tmp_path: Path, *, rewrite: bool) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\n"
        "apps:\n"
        "  api:\n"
        "    path: ${SPACE_PATH}/src/api\n"
        "exports:\n"
        "  venv:\n"
        "    from: api\n"
        "    exec_path: /app/.venv\n"
        "    path: ${API_APP_PATH}/.venv\n"
        f"    rewrite_paths: {'true' if rewrite else 'false'}\n",
        encoding="utf-8",
    )
    return space_file


def _venv_config() -> dict:
    return {
        "services": {
            "api": {
                "image": "demo-api:latest",
                "volumes": [
                    {"type": "bind", "source": "<APIPATH>", "target": "/app"},
                    {"type": "volume", "source": "venv", "target": "/app/.venv"},
                ],
            }
        },
        "volumes": {"venv": {"name": "demo_venv"}},
    }


def test_venv_export_skipped_without_rewrite_paths(tmp_path: Path) -> None:
    """`.venv` export without ``rewrite_paths`` is skipped, not synced (Bug 4)."""
    from cupli.core.loader import load_space

    resolved = load_space(_venv_space(tmp_path, rewrite=False), auto_register=False, auto_cache=False)
    rows = es.sync_exports(resolved, config=_venv_config())
    assert rows[0].status == "skipped"
    assert not resolved.exports["venv"].path.exists()


def test_venv_rewrite_paths_rewrites_pth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``rewrite_paths: true``, container paths in `.pth` become host paths (Bug 4)."""
    from cupli.core.loader import load_space

    resolved = load_space(_venv_space(tmp_path, rewrite=True), auto_register=False, auto_cache=False)
    api_path = resolved.apps["api"].path

    def fake_sync(volume: str, image: str, host_path) -> bool:
        pth_dir = host_path / "lib/python3.13/site-packages"
        pth_dir.mkdir(parents=True, exist_ok=True)
        (pth_dir / "lib.pth").write_text("/app/packages/lib/src\n", encoding="utf-8")
        return True

    monkeypatch.setattr(es, "_docker_sync", fake_sync)
    config = _venv_config()
    config["services"]["api"]["volumes"][0]["source"] = str(api_path)  # /app bind → api host path
    es.sync_exports(resolved, config=config)
    pth = resolved.exports["venv"].path / "lib/python3.13/site-packages/lib.pth"
    content = pth.read_text(encoding="utf-8")
    assert content.strip() == f"{api_path}/packages/lib/src"
    assert "/app/" not in content
