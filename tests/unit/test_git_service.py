"""Tests for :mod:`cupli.services.git_service` filter/checkout logic.

These exercise pure-Python paths (selector filtering, --map resolution,
drift detection) without spawning ``git``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cupli.core.loader import load_space
from cupli.domain.errors import CupliError
from cupli.services import git_service
from cupli.services.git_service import GitRepo, _resolve_checkout_targets, select_repos


def _make_space(tmp_path: Path, *names: str) -> Path:
    """Write a minimal space file with the named apps + fake .git dirs."""
    apps_block = "\n".join(f"  {name}: {{}}" for name in names)
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(f"name: demo\napps:\n{apps_block}\n", encoding="utf-8")
    for name in names:
        app_dir = tmp_path / "src" / "apps" / name
        (app_dir / ".git").mkdir(parents=True)
    return space_file


def _make_repos(*specs: tuple[str, str | None]) -> list[GitRepo]:
    """Build fake :class:`GitRepo` rows for selector/checkout tests."""
    return [GitRepo(name=name, kind="app", path=Path("/tmp") / name, pinned_branch=branch) for name, branch in specs]


def test_select_repos_empty_returns_all(tmp_path: Path) -> None:
    """No selectors → every discovered repo is returned."""
    space_file = _make_space(tmp_path, "api", "web")
    resolved = load_space(space_file)
    repos = select_repos(resolved)
    assert {repo.name for repo in repos} == {"api", "web"}


def test_select_repos_filters_by_name(tmp_path: Path) -> None:
    """Selectors restrict the result to matching components, preserving order."""
    space_file = _make_space(tmp_path, "api", "web", "worker")
    resolved = load_space(space_file)
    repos = select_repos(resolved, ["web", "api"])
    assert [repo.name for repo in repos] == ["web", "api"]


def test_select_repos_unknown_name_raises_e020(tmp_path: Path) -> None:
    """Unknown selector names raise E020 with the names listed."""
    space_file = _make_space(tmp_path, "api")
    resolved = load_space(space_file)
    with pytest.raises(CupliError) as exc:
        select_repos(resolved, ["ghost"])
    assert exc.value.code == "E020"
    assert "ghost" in str(exc.value)


def test_resolve_checkout_targets_uses_default_branch() -> None:
    """Without overrides, every selected repo gets the default branch."""
    repos = _make_repos(("api", None), ("web", None))
    targets = _resolve_checkout_targets(repos, "main", {})
    assert targets == {"api": "main", "web": "main"}


def test_resolve_checkout_targets_overrides_win() -> None:
    """Per-repo overrides win over the default branch."""
    repos = _make_repos(("api", None), ("web", None))
    targets = _resolve_checkout_targets(repos, "main", {"api": "feature/x"})
    assert targets == {"api": "feature/x", "web": "main"}


def test_resolve_checkout_targets_no_default_requires_full_map() -> None:
    """When branch is None, every selected repo must be in overrides."""
    repos = _make_repos(("api", None), ("web", None))
    with pytest.raises(CupliError) as exc:
        _resolve_checkout_targets(repos, None, {"api": "feature/x"})
    assert exc.value.code == "E020"
    assert "web" in str(exc.value)


def test_resolve_checkout_targets_override_outside_selection_raises() -> None:
    """Override naming a repo absent from the selection raises E020."""
    repos = _make_repos(("api", None))
    with pytest.raises(CupliError) as exc:
        _resolve_checkout_targets(repos, "main", {"ghost": "main"})
    assert exc.value.code == "E020"
    assert "ghost" in str(exc.value)


def test_status_row_marks_drifted_when_pinned_branch_differs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A clean repo on a branch other than its pinned one is reported as ``drifted``."""
    repo = GitRepo(name="api", kind="app", path=tmp_path, pinned_branch="main")
    monkeypatch.setattr(git_service.git, "current_branch", lambda _: "feature/x")
    monkeypatch.setattr(git_service.git, "is_clean", lambda _: True)
    monkeypatch.setattr(git_service, "_ahead_behind", lambda _: "in sync")
    row = git_service._status_row(repo)
    assert row.state == "drifted"
    assert "pinned: main" in row.detail


def test_status_row_clean_includes_pinned_in_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A clean, on-pin repo still surfaces its pinned branch in the detail column."""
    repo = GitRepo(name="api", kind="app", path=tmp_path, pinned_branch="main")
    monkeypatch.setattr(git_service.git, "current_branch", lambda _: "main")
    monkeypatch.setattr(git_service.git, "is_clean", lambda _: True)
    monkeypatch.setattr(git_service, "_ahead_behind", lambda _: "")
    row = git_service._status_row(repo)
    assert row.state == "clean"
    assert "pinned: main" in row.detail


def test_status_row_dirty_beats_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An uncommitted-changes repo stays ``dirty`` regardless of pinning."""
    repo = GitRepo(name="api", kind="app", path=tmp_path, pinned_branch="main")
    monkeypatch.setattr(git_service.git, "current_branch", lambda _: "feature/x")
    monkeypatch.setattr(git_service.git, "is_clean", lambda _: False)
    monkeypatch.setattr(git_service, "_ahead_behind", lambda _: "")
    row = git_service._status_row(repo)
    assert row.state == "dirty"
