"""Tests for :mod:`cupli.services.bridge_service`."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

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


def test_derive_host_link_ignores_mounts_own_bind() -> None:
    """A bind whose target == exec_path (the mount's own injected bind) is skipped (Bug 1)."""
    # The app workdir bind (/app) plus the mount's own bind at exec_path; the
    # latter must not win, else `rel` is empty and derivation returns None.
    link = bs.derive_host_link(
        "/app/packages/lib",
        [("/h/app", "/app"), ("/h/mounts/lib", "/app/packages/lib")],
    )
    assert link is not None
    assert link.as_posix() == "/h/app/packages/lib"


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


def test_bridge_conflict_on_nonempty_dir_is_reported_not_raised(tmp_path: Path) -> None:
    """A non-empty directory yields a ``conflict`` result (not a raised error) and is untouched."""
    resolved = _load(tmp_path)
    link = tmp_path / "src/apps/web/packages/ui"
    link.mkdir(parents=True)
    (link / "file.txt").write_text("keep me", encoding="utf-8")
    results = bs.bridge_mounts(resolved)
    assert [r.status for r in results] == ["conflict"]
    assert not link.is_symlink()
    assert (link / "file.txt").read_text(encoding="utf-8") == "keep me"


def test_bridge_conflict_does_not_orphan_earlier_symlink(tmp_path: Path) -> None:
    """A later conflicting mount must not lose the ownership record of an earlier one (Bug 2)."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\n"
        "apps:\n"
        "  web: {}\n"
        "mounts:\n"
        "  good:\n"
        "    hosted_in: [web]\n"
        "    path: ${MOUNTS_PATH}/good\n"
        "    exec_path: /app/packages/good\n"
        "    host_bridge:\n"
        "      link: ${WEB_APP_PATH}/packages/good\n"
        "  bad:\n"
        "    hosted_in: [web]\n"
        "    path: ${MOUNTS_PATH}/bad\n"
        "    exec_path: /app/packages/bad\n"
        "    host_bridge:\n"
        "      link: ${WEB_APP_PATH}/packages/bad\n",
        encoding="utf-8",
    )
    from cupli.core.loader import load_space

    resolved = load_space(space_file, auto_register=False, auto_cache=False)
    bad_link = tmp_path / "src/apps/web/packages/bad"
    bad_link.mkdir(parents=True)
    (bad_link / "keep").write_text("x", encoding="utf-8")  # forces a conflict on `bad`
    bs.bridge_mounts(resolved)
    # `good` was created and must remain cupli-owned despite `bad` conflicting.
    removed = {r.name: r.status for r in bs.unbridge_mounts(resolved, ["good"])}
    assert removed["good"] == "removed"
    assert not (tmp_path / "src/apps/web/packages/good").exists()


@needs_symlinks
def test_bridge_replaces_empty_dir_without_e032(tmp_path: Path) -> None:
    """An empty directory on the link path is removed and replaced with a symlink (Bug 2)."""
    resolved = _load(tmp_path)
    link = tmp_path / "src/apps/web/packages/ui"
    link.mkdir(parents=True)  # empty mount point left by docker / a prior run
    results = bs.bridge_mounts(resolved)
    assert [r.status for r in results] == ["created"]
    assert link.is_symlink()
    assert (link.parent / link.readlink()).resolve() == (tmp_path / "src/mounts/ui-lib").resolve()


def test_link_status_classifies_empty_vs_conflict(tmp_path: Path) -> None:
    """``link_status`` distinguishes reclaimable stubs from real content."""
    target = tmp_path / "target"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert bs.link_status(empty, target) == "empty"
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "f").write_text("x", encoding="utf-8")
    assert bs.link_status(nonempty, target) == "conflict"
    zero_file = tmp_path / "stub.yml"
    zero_file.touch()  # 0-byte docker mount-point stub
    assert bs.link_status(zero_file, target) == "empty"
    real_file = tmp_path / "real.yml"
    real_file.write_text("data", encoding="utf-8")
    assert bs.link_status(real_file, target) == "conflict"


@needs_symlinks
def test_bridge_replaces_zero_byte_file_stub(tmp_path: Path) -> None:
    """A 0-byte file stub (docker mount-point, e.g. mkdocs.yml) is replaced by a symlink (Bug 3b)."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\n"
        "apps:\n"
        "  web: {}\n"
        "mounts:\n"
        "  cfg:\n"
        "    hosted_in: [web]\n"
        "    path: ${MOUNTS_PATH}/cfg.yml\n"
        "    exec_path: /app/cfg.yml\n"
        "    host_bridge:\n"
        "      link: ${WEB_APP_PATH}/cfg.yml\n",
        encoding="utf-8",
    )
    from cupli.core.loader import load_space

    resolved = load_space(space_file, auto_register=False, auto_cache=False)
    stub = tmp_path / "src/apps/web/cfg.yml"
    stub.parent.mkdir(parents=True)
    stub.touch()  # 0-byte stub left by the docker daemon
    results = bs.bridge_mounts(resolved)
    assert [r.status for r in results] == ["created"]
    assert stub.is_symlink()


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


@needs_symlinks
def test_bridge_auto_derive_uses_hosting_app_bind_only(tmp_path: Path) -> None:
    """Auto-derivation uses the hosting app's workdir bind, not another app's /app bind (Bug 1)."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\n"
        "apps:\n"
        "  web: {}\n"
        "  api: {}\n"
        "mounts:\n"
        "  ui:\n"
        "    hosted_in: [web]\n"
        "    path: ${MOUNTS_PATH}/ui-lib\n"
        "    exec_path: /app/packages/ui\n"
        "    host_bridge: true\n",  # auto-derive, no explicit link
        encoding="utf-8",
    )
    from cupli.core.loader import load_space

    resolved = load_space(space_file, auto_register=False, auto_cache=False)
    web_src = str(tmp_path / "src/apps/web")
    api_src = str(tmp_path / "src/apps/api")
    # Both apps bind their own dir to /app; the link must land under web (the host).
    config = {
        "services": {
            "web": {"volumes": [{"type": "bind", "source": web_src, "target": "/app"}]},
            "api": {"volumes": [{"type": "bind", "source": api_src, "target": "/app"}]},
        }
    }
    results = bs.bridge_mounts(resolved, config=config)
    assert [r.status for r in results] == ["created"]
    link = tmp_path / "src/apps/web/packages/ui"
    assert link.is_symlink()
    assert "src/apps/api" not in str(link.parent / link.readlink())


def test_bridge_skipped_when_mount_detached(tmp_path: Path) -> None:
    """A detached mount is not bridged."""
    from cupli.services.mounts_service import detach

    resolved = _load(tmp_path)
    detach(resolved, "ui")
    assert bs.bridge_mounts(resolved) == []
