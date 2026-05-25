"""Multi-repo git use cases.

Iterates over every cloned working copy in the space (apps + bases + mounts
with ``repo`` set) and runs read-only or fast-forward git operations in
parallel where safe.

Returned :class:`GitRow` objects describe per-repo state; the CLI layer
renders them with rich.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cupli.utils import git
from cupli.utils.console import debug

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from cupli.core.loader import ResolvedSpace


@dataclass(frozen=True)
class GitRepo:
    """One discovered working copy + the component kind it came from."""

    name: str
    kind: str
    path: Path
    pinned_branch: str | None = None
    """``branch:`` declared in the space file, or ``None`` when unpinned."""


@dataclass(frozen=True)
class GitRow:
    """One row of ``cupli git status`` / ``cupli git pull``."""

    name: str
    kind: str
    path: Path
    branch: str
    state: str
    """``clean`` / ``dirty`` / ``missing`` / ``error`` / ``up-to-date`` / ``pulled``."""
    detail: str = ""


def discover_repos(resolved: ResolvedSpace) -> list[GitRepo]:
    """Return every component (app/base/mount) whose ``path`` is a git repo."""
    repos: list[GitRepo] = []
    for name in resolved.space.apps:
        path = resolved.apps[name].path
        if git.is_git_repo(path):
            repos.append(GitRepo(name=name, kind="app", path=path, pinned_branch=resolved.space.apps[name].branch))
    for name in resolved.space.bases:
        path = resolved.bases[name].path
        if git.is_git_repo(path):
            repos.append(GitRepo(name=name, kind="base", path=path, pinned_branch=resolved.space.bases[name].branch))
    for name in resolved.space.mounts:
        path = resolved.mounts[name].path
        if git.is_git_repo(path):
            repos.append(GitRepo(name=name, kind="mount", path=path, pinned_branch=resolved.space.mounts[name].branch))
    return repos


def select_repos(
    resolved: ResolvedSpace,
    selectors: Iterable[str] | None = None,
) -> list[GitRepo]:
    """Discover repos, then filter by ``selectors`` (case-sensitive component names).

    Raises:
        CupliError: ``E020`` when a selector matches no discovered repo.
    """
    repos = discover_repos(resolved)
    names = list(selectors or [])
    if not names:
        return repos
    by_name = {repo.name: repo for repo in repos}
    selected: list[GitRepo] = []
    unknown: list[str] = []
    for name in names:
        repo = by_name.get(name)
        if repo is None:
            unknown.append(name)
            continue
        selected.append(repo)
    if unknown:
        from cupli.domain.errors import CupliError

        raise CupliError("E020", name=", ".join(unknown))
    return selected


def status(
    resolved: ResolvedSpace,
    *,
    selectors: Iterable[str] | None = None,
    workers: int = 4,
) -> list[GitRow]:
    """Compute per-repo status rows in parallel for the selected repos."""
    repos = select_repos(resolved, selectors)
    return _parallel(repos, _status_row, workers=workers)


def pull(
    resolved: ResolvedSpace,
    *,
    selectors: Iterable[str] | None = None,
    rebase: bool = False,
    workers: int = 4,
) -> list[GitRow]:
    """Run ``git pull --ff-only`` (or ``--rebase``) per selected repo in parallel."""
    repos = select_repos(resolved, selectors)
    return _parallel(repos, lambda repo: _pull_row(repo, rebase=rebase), workers=workers)


def fetch(
    resolved: ResolvedSpace,
    *,
    selectors: Iterable[str] | None = None,
    workers: int = 4,
) -> list[GitRow]:
    """Run ``git fetch --prune`` per selected repo in parallel."""
    repos = select_repos(resolved, selectors)
    return _parallel(repos, _fetch_row, workers=workers)


def checkout(
    resolved: ResolvedSpace,
    branch: str | None,
    *,
    selectors: Iterable[str] | None = None,
    overrides: dict[str, str] | None = None,
    workers: int = 4,
) -> list[GitRow]:
    """Run ``git checkout`` per selected repo.

    Args:
        resolved: loaded space passed through ``select_repos``.
        branch: default branch applied to every selected repo not in ``overrides``.
        selectors: optional whitelist of component names.
        overrides: per-repo ``{name: branch}`` overrides (wins over ``branch``).
        workers: max parallel ``git checkout`` invocations.

    Raises:
        CupliError: ``E020`` when an ``overrides`` key is not in the selection
            or when ``branch`` is ``None`` and some selected repo has no override.
    """
    repos = select_repos(resolved, selectors)
    targets = _resolve_checkout_targets(repos, branch, overrides or {})
    return _parallel(
        repos,
        lambda repo: _checkout_row(repo, branch=targets[repo.name]),
        workers=workers,
    )


def _resolve_checkout_targets(
    repos: list[GitRepo],
    branch: str | None,
    overrides: dict[str, str],
) -> dict[str, str]:
    """Build a ``{repo_name: target_branch}`` map; raise on missing branches."""
    from cupli.domain.errors import CupliError

    selected_names = {repo.name for repo in repos}
    extra = sorted(name for name in overrides if name not in selected_names)
    if extra:
        raise CupliError("E020", name=", ".join(extra))
    targets: dict[str, str] = {}
    missing: list[str] = []
    for repo in repos:
        target = overrides.get(repo.name, branch)
        if target is None:
            missing.append(repo.name)
            continue
        targets[repo.name] = target
    if missing:
        raise CupliError("E020", name=f"branch required for: {', '.join(missing)}")
    return targets


# --- per-repo workers ------------------------------------------------------


def _parallel(
    repos: Iterable[GitRepo],
    worker,
    *,
    workers: int,
) -> list[GitRow]:
    """Run ``worker(repo)`` in a thread pool, preserving discovery order."""
    repos_list = list(repos)
    out: dict[int, GitRow] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(worker, repo): index for index, repo in enumerate(repos_list)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                out[index] = future.result()
            except Exception as exc:
                repo = repos_list[index]
                out[index] = GitRow(
                    name=repo.name,
                    kind=repo.kind,
                    path=repo.path,
                    branch="?",
                    state="error",
                    detail=str(exc),
                )
    return [out[idx] for idx in sorted(out)]


def _status_row(repo: GitRepo) -> GitRow:
    """Compute the status row for one repo.

    The row's ``state`` is ``"drifted"`` (yellow) when the working tree's
    current branch differs from the ``branch:`` pinned in the space file —
    ``"dirty"`` still wins when there are uncommitted changes.
    """
    branch = _safe(lambda: git.current_branch(repo.path), fallback="?")
    clean = _safe(lambda: git.is_clean(repo.path), fallback=False)
    detail = _ahead_behind(repo.path)
    if not clean:
        state = "dirty"
    elif repo.pinned_branch and branch != repo.pinned_branch:
        state = "drifted"
        suffix = f"pinned: {repo.pinned_branch}"
        detail = f"{detail}; {suffix}" if detail else suffix
    else:
        state = "clean"
        if repo.pinned_branch:
            suffix = f"pinned: {repo.pinned_branch}"
            detail = f"{detail}; {suffix}" if detail else suffix
    return GitRow(name=repo.name, kind=repo.kind, path=repo.path, branch=branch, state=state, detail=detail)


def _pull_row(repo: GitRepo, *, rebase: bool) -> GitRow:
    """Run pull on one repo and report the outcome."""
    debug(f"git pull: {repo.name} ({repo.path})")
    args = ["git", "pull", "--ff-only"] if not rebase else ["git", "pull", "--rebase"]
    completed = subprocess.run(
        args,
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    branch = _safe(lambda: git.current_branch(repo.path), fallback="?")
    if completed.returncode != 0:
        return GitRow(
            name=repo.name,
            kind=repo.kind,
            path=repo.path,
            branch=branch,
            state="error",
            detail=completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "git pull failed",
        )
    stdout = completed.stdout.strip()
    state = "up-to-date" if "Already up to date" in stdout else "pulled"
    return GitRow(
        name=repo.name,
        kind=repo.kind,
        path=repo.path,
        branch=branch,
        state=state,
        detail=stdout.splitlines()[-1] if stdout else "",
    )


def _fetch_row(repo: GitRepo) -> GitRow:
    """Run fetch on one repo and report the outcome."""
    completed = subprocess.run(
        ["git", "fetch", "--prune"],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    branch = _safe(lambda: git.current_branch(repo.path), fallback="?")
    if completed.returncode != 0:
        return GitRow(
            name=repo.name,
            kind=repo.kind,
            path=repo.path,
            branch=branch,
            state="error",
            detail=completed.stderr.strip(),
        )
    return GitRow(
        name=repo.name, kind=repo.kind, path=repo.path, branch=branch, state="fetched", detail=_ahead_behind(repo.path)
    )


def _checkout_row(repo: GitRepo, *, branch: str) -> GitRow:
    """Switch a single repo to ``branch``."""
    completed = subprocess.run(
        ["git", "checkout", branch],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    new_branch = _safe(lambda: git.current_branch(repo.path), fallback="?")
    if completed.returncode != 0:
        return GitRow(
            name=repo.name,
            kind=repo.kind,
            path=repo.path,
            branch=new_branch,
            state="error",
            detail=completed.stderr.strip(),
        )
    return GitRow(name=repo.name, kind=repo.kind, path=repo.path, branch=new_branch, state="checked-out", detail="")


def _ahead_behind(path: Path) -> str:
    """Return a short ``ahead N / behind M`` indicator (best-effort)."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return ""
    behind, ahead = parts
    if behind == "0" and ahead == "0":
        return "in sync"
    return f"ahead {ahead} / behind {behind}"


def _safe(callable_, *, fallback):
    """Run ``callable_`` swallowing exceptions, returning ``fallback`` on error."""
    try:
        return callable_()
    except (subprocess.CalledProcessError, OSError):
        return fallback


__all__ = (
    "GitRepo",
    "GitRow",
    "checkout",
    "discover_repos",
    "fetch",
    "pull",
    "select_repos",
    "status",
)
