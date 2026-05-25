"""Git helpers used by clone / sync / set-hooks pipelines."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from cupli.domain.errors import CupliError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def is_git_repo(path: Path) -> bool:
    """Return True when ``path`` contains a ``.git`` directory."""
    return path.joinpath(".git").exists()


def have_git() -> bool:  # pragma: no cover
    """Return True when the ``git`` executable is on PATH."""
    try:
        subprocess.check_output(["git", "--help"], stderr=subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def git_revision(path: Path) -> str:
    """Return the short HEAD revision of the git working copy at ``path``.

    Raises ``CalledProcessError`` (with captured stderr) for repos without
    any commits — callers wrap this in ``_safe`` to fall back to ``"?"``.
    """
    return (
        subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=path,
            stderr=subprocess.PIPE,
        )
        .decode("utf-8")
        .strip()
    )


def current_branch(path: Path) -> str:
    """Return the current branch name at ``path``.

    Falls back to a low-noise rendering on freshly-initialised repos: when
    HEAD doesn't resolve yet, returns the symbolic ref name (e.g. ``main``)
    instead of failing.
    """
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=path,
                stderr=subprocess.PIPE,
            )
            .decode("utf-8")
            .strip()
        )
    except subprocess.CalledProcessError:
        return _symbolic_head(path)


def _symbolic_head(path: Path) -> str:
    """Read ``HEAD`` symbolically when no commits exist yet.

    Returns the short branch name (``main``) or ``"?"`` if even that fails.
    """
    try:
        out = subprocess.check_output(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=path,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError:
        return "?"
    return out.decode("utf-8").strip() or "?"


def is_clean(path: Path) -> bool:
    """Return True when ``path`` has no uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )
    return not result.stdout.strip()


def clone_repo(
    repo: str,
    dest: Path,
    *,
    branch: str | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Clone ``repo`` into ``dest``.

    Args:
        repo: source URL or path passed to ``git clone``.
        dest: target directory.
        branch: optional branch to check out via ``-b <branch>``.
        env: optional environment for the subprocess.

    Raises:
        CupliError: ``E017`` when ``git clone`` exits non-zero.
    """
    argv = ["git", "clone"]
    if branch:
        argv.extend(["-b", branch])
    argv.extend([repo, str(dest)])
    try:
        subprocess.check_output(argv, env=env, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        raise CupliError("E017", repo=repo, dest=str(dest), exit_code=exc.returncode) from exc


def list_tracked_repos(roots: Iterable[Path]) -> list[Path]:
    """Discover every git working copy directly under any of ``roots``."""
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(entry for entry in root.iterdir() if entry.is_dir() and is_git_repo(entry))
    return found


__all__ = (
    "clone_repo",
    "current_branch",
    "git_revision",
    "have_git",
    "is_clean",
    "is_git_repo",
    "list_tracked_repos",
)
