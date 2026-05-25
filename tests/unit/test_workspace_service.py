"""Tests for :mod:`cupli.services.workspace_service`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cupli.core import registry
from cupli.core.loader import load_space
from cupli.domain.errors import CupliError
from cupli.services.workspace_service import (
    doctor_space,
    scaffold_space,
    sync_space,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the registry path into a per-test temporary file."""
    registry_path = tmp_path / "spaces.json"
    monkeypatch.setattr(registry, "spaces_registry_path", lambda: registry_path)
    return registry_path


# --- scaffold --------------------------------------------------------------


def test_scaffold_creates_state_dir_and_files(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``scaffold_space`` creates the space file, env file, and ``.locals`` only.

    ``src/apps``, ``src/bases``, ``src/mounts`` are created lazily by
    ``sync_space`` and other use-cases when first needed.
    """
    _ = isolated_registry
    target = tmp_path / "demo"
    result = scaffold_space(name="demo", target_dir=target)
    assert result.space_path == target / "space.cupli.yaml"
    assert result.space_path.exists()
    assert (target / ".locals").is_dir()
    assert (target / ".env").exists()
    assert not (target / "src" / "apps").exists()
    assert not (target / "src" / "bases").exists()
    assert not (target / "src" / "mounts").exists()


def test_scaffold_registers_in_registry(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``scaffold_space`` adds the new space to the registry."""
    _ = isolated_registry
    target = tmp_path / "demo"
    scaffold_space(name="demo", target_dir=target)
    assert registry.list_known_spaces() == {"demo": target / "space.cupli.yaml"}


def test_scaffold_refuses_existing_without_force(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """Existing space file raises ``E029`` unless ``force=True``."""
    _ = isolated_registry
    target = tmp_path / "demo"
    scaffold_space(name="demo", target_dir=target)
    with pytest.raises(CupliError) as exc_info:
        scaffold_space(name="demo", target_dir=target)
    assert exc_info.value.code == "E029"


def test_scaffold_overwrites_with_force(
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``force=True`` rewrites the space file in place."""
    _ = isolated_registry
    target = tmp_path / "demo"
    scaffold_space(name="demo", target_dir=target)
    (target / "space.cupli.yaml").write_text("name: stale\napps:\n  api: {}\n", encoding="utf-8")
    scaffold_space(name="demo", target_dir=target, force=True)
    body = (target / "space.cupli.yaml").read_text(encoding="utf-8")
    assert "name: demo" in body


# --- sync ------------------------------------------------------------------


def _write_space_with_repos(tmp_path: Path) -> Path:
    """Build a fixture space with two apps + one mount, all repo-backed."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        (
            "name: sync-fix\n"
            "apps:\n"
            "  api:\n"
            "    repo: git@github.com:example/api.git\n"
            "  worker:\n"
            "    repo: git@github.com:example/worker.git\n"
            "mounts:\n"
            "  sdk:\n"
            "    repo: git@github.com:example/sdk.git\n"
            "    hosted_in: [api]\n"
            "    exec_path: /opt/sdk\n"
        ),
        encoding="utf-8",
    )
    return space_file


def test_sync_clones_missing_repos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sync_space`` invokes ``git.clone_repo`` for every missing repo."""
    space_file = _write_space_with_repos(tmp_path)

    cloned: list[tuple[str, str]] = []

    def fake_clone(repo: str, dest, *, branch=None, env=None) -> None:
        cloned.append((repo, str(dest)))
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".git").mkdir()

    from cupli.services import workspace_service as service

    monkeypatch.setattr(service.git, "clone_repo", fake_clone)

    resolved = load_space(space_file)
    report = sync_space(resolved, workers=1)
    assert set(report.cloned) == {"api", "worker", "sdk"}
    assert {item[0] for item in cloned} == {
        "git@github.com:example/api.git",
        "git@github.com:example/worker.git",
        "git@github.com:example/sdk.git",
    }


def test_sync_forwards_branch_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``branch:`` declared on the component is forwarded to ``clone_repo``."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\napps:\n  api:\n    repo: git@github.com:example/api.git\n    branch: develop\n",
        encoding="utf-8",
    )
    seen_branches: list[str | None] = []

    def fake_clone(repo: str, dest, *, branch=None, env=None) -> None:
        seen_branches.append(branch)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".git").mkdir()

    from cupli.services import workspace_service as service

    monkeypatch.setattr(service.git, "clone_repo", fake_clone)

    resolved = load_space(space_file)
    sync_space(resolved, workers=1)
    assert seen_branches == ["develop"]


def test_sync_skips_already_cloned_repos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target that already contains ``.git`` is reported as skipped."""
    space_file = _write_space_with_repos(tmp_path)

    # Pre-create one of the targets as a fake git working copy.
    api_path = tmp_path / "src" / "apps" / "api"
    api_path.mkdir(parents=True)
    (api_path / ".git").mkdir()

    def fake_clone(repo: str, dest, *, branch=None, env=None) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".git").mkdir()

    from cupli.services import workspace_service as service

    monkeypatch.setattr(service.git, "clone_repo", fake_clone)

    report = sync_space(load_space(space_file), workers=1)
    assert "api" in report.skipped


def test_sync_only_apps_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``include_apps=True, include_bases=False, include_mounts=False`` is honoured."""
    space_file = _write_space_with_repos(tmp_path)

    seen: list[str] = []

    def fake_clone(repo: str, dest, *, branch=None, env=None) -> None:
        seen.append(repo)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".git").mkdir()

    from cupli.services import workspace_service as service

    monkeypatch.setattr(service.git, "clone_repo", fake_clone)

    sync_space(
        load_space(space_file),
        include_apps=True,
        include_bases=False,
        include_mounts=False,
        workers=1,
    )
    assert all("sdk" not in url for url in seen)


def test_sync_reports_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures are collected into ``SyncReport.failed`` and do not raise."""
    space_file = _write_space_with_repos(tmp_path)

    def fake_clone(repo: str, dest, *, branch=None, env=None) -> None:
        raise CupliError("E017", repo=repo, dest=str(dest), exit_code=128)

    from cupli.services import workspace_service as service

    monkeypatch.setattr(service.git, "clone_repo", fake_clone)

    report = sync_space(load_space(space_file), workers=1)
    assert {name for name, _ in report.failed} == {"api", "worker", "sdk"}


# --- doctor ----------------------------------------------------------------


def test_doctor_flags_missing_clones(tmp_path: Path) -> None:
    """``doctor_space`` warns for repo-declared components that are not cloned."""
    space_file = _write_space_with_repos(tmp_path)
    report = doctor_space(load_space(space_file))
    joined = " ".join(report.warnings)
    assert "api" in joined
    assert "worker" in joined
    assert "sdk" in joined


def test_doctor_clean_when_paths_exist(tmp_path: Path) -> None:
    """A repoless app whose path exists shows up as OK."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text("name: clean\napps:\n  api: {}\n", encoding="utf-8")
    (tmp_path / "src" / "apps" / "api").mkdir(parents=True)
    report = doctor_space(load_space(space_file))
    assert any("api" in row for row in report.ok)
    assert not report.errors
