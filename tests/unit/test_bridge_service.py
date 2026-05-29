"""Tests for :mod:`cupli.services.bridge_service`."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cupli.domain.errors import CupliError
from cupli.services import bridge_service as bs


def _symlinks_supported() -> bool:
    """True when the platform/user can create symlinks (false on locked-down Windows)."""
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe"
        try:
            probe.symlink_to(tmp)
        except OSError:
            return False
        return True


needs_symlinks = pytest.mark.skipif(not _symlinks_supported(), reason="platform cannot create symlinks")


# --- pure helpers ----------------------------------------------------------


def test_derive_host_link_picks_longest_ancestor_bind() -> None:
    """The bind whose target is the longest ancestor wins."""
    link = bs.derive_host_link(
        "/app/packages/sdk",
        [("/h/app", "/app"), ("/h/pkgs", "/app/packages")],
    )
    assert link is not None
    # Compare via as_posix so the assertion holds on Windows runners too
    # (Path renders OS-native separators; the feature targets Linux/macOS/WSL2).
    assert link.as_posix() == "/h/pkgs/sdk"


def test_derive_host_link_none_when_no_bind_contains_path() -> None:
    """A path outside every bind yields no host link."""
    assert bs.derive_host_link("/elsewhere", [("/h/app", "/app")]) is None


def test_binds_for_services_only_bind_volumes_of_named_services() -> None:
    """Only ``type: bind`` volumes of the requested services are returned."""
    config = {
        "services": {
            "web": {
                "volumes": [
                    {"type": "bind", "source": "/h/app", "target": "/app"},
                    {"type": "volume", "source": "nm", "target": "/app/node_modules"},
                ]
            },
            "other": {"volumes": [{"type": "bind", "source": "/x", "target": "/x"}]},
        }
    }
    assert bs.binds_for_services(config, {"web"}) == [("/h/app", "/app")]


# --- symlink lifecycle (explicit link, no docker) --------------------------


def _space(tmp_path: Path) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\n"
        "apps:\n"
        "  web: {}\n"
        "mounts:\n"
        "  ui:\n"
        "    hosted_in: [web]\n"
        "    path: ${MOUNTS_PATH}/ui-lib\n"
        "    exec_path: /app/packages/ui\n"
        "    host_bridge:\n"
        "      link: ${WEB_APP_PATH}/packages/ui\n",
        encoding="utf-8",
    )
    return space_file


def _load(tmp_path: Path):
    from cupli.core.loader import load_space

    return load_space(_space(tmp_path), auto_register=False, auto_cache=False)


@needs_symlinks
def test_bridge_creates_relative_symlink(tmp_path: Path) -> None:
    """``bridge_mounts`` creates a relative symlink pointing at the mount path."""
    resolved = _load(tmp_path)
    results = bs.bridge_mounts(resolved)
    assert [r.status for r in results] == ["created"]
    link = tmp_path / "src/apps/web/packages/ui"
    assert link.is_symlink()
    target = tmp_path / "src/mounts/ui-lib"
    assert (link.parent / link.readlink()).resolve() == target.resolve()


@needs_symlinks
def test_bridge_is_idempotent(tmp_path: Path) -> None:
    """A second bridge run reports ``ok`` and does not recreate the link."""
    resolved = _load(tmp_path)
    bs.bridge_mounts(resolved)
    second = bs.bridge_mounts(resolved)
    assert [r.status for r in second] == ["ok"]


@needs_symlinks
def test_bridge_repairs_broken_symlink(tmp_path: Path) -> None:
    """A symlink pointing somewhere else is re-pointed at the mount path."""
    resolved = _load(tmp_path)
    link = tmp_path / "src/apps/web/packages/ui"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "wrong-target")
    results = bs.bridge_mounts(resolved)
    assert [r.status for r in results] == ["repaired"]
    assert (link.parent / link.readlink()).resolve() == (tmp_path / "src/mounts/ui-lib").resolve()


def test_bridge_conflict_on_real_dir_raises_e032(tmp_path: Path) -> None:
    """A real (non-symlink) directory on the link path is never overwritten."""
    resolved = _load(tmp_path)
    link = tmp_path / "src/apps/web/packages/ui"
    link.mkdir(parents=True)
    (link / "file.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(CupliError) as exc:
        bs.bridge_mounts(resolved)
    assert exc.value.code == "E032"
    assert (link / "file.txt").read_text(encoding="utf-8") == "keep me"


@needs_symlinks
def test_unbridge_removes_only_cupli_created_symlink(tmp_path: Path) -> None:
    """``unbridge_mounts`` removes the tracked symlink and forgets it."""
    resolved = _load(tmp_path)
    bs.bridge_mounts(resolved)
    link = tmp_path / "src/apps/web/packages/ui"
    assert link.is_symlink()
    results = bs.unbridge_mounts(resolved)
    assert [r.status for r in results] == ["removed"]
    assert not link.exists()
    # A second unbridge is a no-op (nothing tracked).
    assert bs.unbridge_mounts(resolved) == []


@needs_symlinks
def test_bridge_info_reports_pending_then_ok(tmp_path: Path) -> None:
    """``bridge_info`` is ``pending`` before creation and ``ok`` afterwards."""
    resolved = _load(tmp_path)
    assert bs.bridge_info(resolved)["ui"].status == "pending"
    bs.bridge_mounts(resolved)
    assert bs.bridge_info(resolved)["ui"].status == "ok"


def test_bridge_skipped_when_mount_detached(tmp_path: Path) -> None:
    """A detached mount is not bridged."""
    from cupli.services.mounts_service import detach

    resolved = _load(tmp_path)
    detach(resolved, "ui")
    assert bs.bridge_mounts(resolved) == []
