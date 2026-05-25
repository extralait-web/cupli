"""Tests for :mod:`cupli.utils.git`."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from cupli.domain.errors import CupliError
from cupli.utils.git import (
    clone_repo,
    current_branch,
    git_revision,
    is_clean,
    is_git_repo,
    list_tracked_repos,
)

if TYPE_CHECKING:
    from pathlib import Path


def _init_repo(path: Path, *, with_commit: bool = True) -> Path:
    """Create a real git repository on disk and optionally seed one commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], check=True)
    if with_commit:
        (path / "README.md").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


def test_is_git_repo_detects_dot_git(tmp_path: Path) -> None:
    """A directory with ``.git`` inside is recognised as a repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    assert is_git_repo(repo) is True


def test_is_git_repo_returns_false_for_plain_dir(tmp_path: Path) -> None:
    """A bare directory without ``.git`` is rejected."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_repo(plain) is False


def test_git_revision_returns_short_sha(tmp_path: Path) -> None:
    """``git rev-parse --short HEAD`` returns a short hex digest."""
    repo = _init_repo(tmp_path / "repo")
    rev = git_revision(repo)
    assert len(rev) >= 4
    assert all(char in "0123456789abcdef" for char in rev)


def test_current_branch_returns_initial_branch(tmp_path: Path) -> None:
    """A fresh repo with a commit reports its initial branch."""
    repo = _init_repo(tmp_path / "repo")
    assert current_branch(repo) == "main"


def test_current_branch_falls_back_to_symbolic_head(tmp_path: Path) -> None:
    """A pre-commit repo still resolves its branch name via the symbolic ref."""
    repo = _init_repo(tmp_path / "repo", with_commit=False)
    assert current_branch(repo) == "main"


def test_current_branch_returns_question_mark_when_unresolvable(tmp_path: Path) -> None:
    """Without ``.git`` at all, fall back to ``"?"`` instead of raising."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert current_branch(plain) == "?"


def test_is_clean_true_on_freshly_committed_repo(tmp_path: Path) -> None:
    """A repo with nothing in the working tree is clean."""
    repo = _init_repo(tmp_path / "repo")
    assert is_clean(repo) is True


def test_is_clean_false_when_workdir_has_changes(tmp_path: Path) -> None:
    """An untracked file makes ``is_clean`` return False."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "new.txt").write_text("change", encoding="utf-8")
    assert is_clean(repo) is False


def test_clone_repo_copies_history(tmp_path: Path) -> None:
    """``clone_repo`` mirrors a source repo into ``dest``."""
    src = _init_repo(tmp_path / "src")
    dest = tmp_path / "dest"
    clone_repo(str(src), dest)
    assert (dest / ".git").is_dir()
    assert (dest / "README.md").exists()


def test_clone_repo_raises_e017_on_failure(tmp_path: Path) -> None:
    """A missing source produces ``CupliError E017``."""
    with pytest.raises(CupliError) as exc_info:
        clone_repo(str(tmp_path / "does-not-exist"), tmp_path / "dest")
    assert exc_info.value.code == "E017"


def test_list_tracked_repos_skips_non_directories(tmp_path: Path) -> None:
    """Non-directory entries under a root are ignored."""
    root = tmp_path / "root"
    root.mkdir()
    repo_a = _init_repo(root / "a")
    repo_b = _init_repo(root / "b")
    (root / "loose.txt").write_text("nope", encoding="utf-8")
    discovered = list_tracked_repos([root])
    assert sorted(discovered) == sorted([repo_a, repo_b])


def test_list_tracked_repos_ignores_missing_root(tmp_path: Path) -> None:
    """Roots that don't exist are skipped silently."""
    repo_a = _init_repo(tmp_path / "a")
    discovered = list_tracked_repos([tmp_path / "missing", tmp_path])
    assert repo_a in discovered
