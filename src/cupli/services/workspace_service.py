"""Workspace lifecycle use cases.

Implements the actions surfaced through ``cli/workspace.py``:

- :func:`scaffold_space`: ``cupli init`` writes a fresh ``space.cupli.yaml``
  and the default directory layout, then registers the result.
- :func:`sync_space`: ``cupli space sync`` clones every declared repo in
  parallel and fires each component's ``post_clone`` once on success.
- :func:`doctor_space`: ``cupli space doctor`` walks the resolved space and
  emits a structured health report.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cupli.core import registry
from cupli.domain.consts import DEFAULT_LOCALS_DIR
from cupli.domain.errors import CupliError
from cupli.utils import git
from cupli.utils.console import debug, info, warn
from cupli.utils.path import create_dir, create_file
from cupli.utils.subprocess import run_command

if TYPE_CHECKING:
    from pathlib import Path

    from cupli.core.loader import ResolvedSpace


SPACE_TEMPLATE = """\
# yaml-language-server: $schema=https://raw.githubusercontent.com/extralait-web/cupli/main/space.schema.json
# space.cupli.yaml — scaffolded by `cupli init`.
#
# Quick-start:
#   cupli up                 # build + start everything
#   cupli ps                 # what's running
#   cupli logs <svc> -f      # tail logs
#   cupli down               # tear down
#
# Reference: https://github.com/extralait-web/cupli/blob/main/README.md
# Editing as an AI agent? See AGENTS.md.

schema_version: 1
name: {name}
cupli_min: 0.1.0

# Top-level variables visible to every app, base, and mount.
vars: {{}}

# Declared applications. Each app binds to one or more docker-compose services.
# Pick one of the four forms (see README.md ▸ Service binding forms).
apps:

  # Form 3 — inline single-service spec, no compose file needed.
  # Any docker-compose attribute (image, build, command, environment, ...) is valid.
  example:
    service:
      image: alpine:3.20
      command: ["sh", "-c", "echo hello && sleep 3600"]
    vars: {{}}

  # Form 4 — compound app (uncomment to try).
  # backend:
  #   vars:
  #     DATABASE_URL: postgres://...
  #   services:
  #     backend:
  #       image: ${{IMAGE}}
  #       command: [uvicorn, app.main:app]
  #     celery-worker:
  #       image: ${{IMAGE}}
  #       command: [celery, -A, app.tasks, worker]
"""


# --- scaffold --------------------------------------------------------------


@dataclass(frozen=True)
class ScaffoldResult:
    """Outcome of :func:`scaffold_space`.

    Attributes:
        space_path: absolute path of the scaffolded ``space.cupli.yaml``.
        created_dirs: directories created on disk.
        created_files: files created on disk.
    """

    space_path: Path
    created_dirs: tuple[Path, ...]
    created_files: tuple[Path, ...]


def scaffold_space(*, name: str, target_dir: Path, force: bool = False) -> ScaffoldResult:
    """Scaffold a new cupli space at ``target_dir``.

    Args:
        name: identifier for the new space (used as docker network name).
        target_dir: absolute directory that will host the space.
        force: when True, overwrite an existing ``space.cupli.yaml``.

    Returns:
        :class:`ScaffoldResult` describing every artefact created.

    Raises:
        CupliError: ``E029`` when a space file already exists and
            ``force=False``.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    space_file = target_dir / "space.cupli.yaml"
    if space_file.exists() and not force:
        raise CupliError("E029", path=str(space_file))

    dirs = (target_dir / DEFAULT_LOCALS_DIR,)
    for one in dirs:
        create_dir(one)

    space_file.write_text(SPACE_TEMPLATE.format(name=name), encoding="utf-8")
    env_file = target_dir / ".env"
    create_file(env_file)

    registry.add_space(name, space_file)

    return ScaffoldResult(
        space_path=space_file,
        created_dirs=dirs,
        created_files=(space_file, env_file),
    )


# --- sync ------------------------------------------------------------------


@dataclass(frozen=True)
class SyncTarget:
    """One component selected for cloning.

    Attributes:
        name: declared component name.
        path: absolute target directory on the host.
        repo: git URL to clone (already substituted).
        branch: optional branch checked out at clone time (``-b <branch>``).
        post_clone: optional shell command run after a successful clone.
        init_vars: env vars exported for clone and post_clone.
    """

    name: str
    path: Path
    repo: str
    branch: str | None
    post_clone: str | None
    init_vars: dict[str, str]


@dataclass
class SyncReport:
    """Aggregate result of :func:`sync_space`."""

    cloned: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def sync_space(
    resolved: ResolvedSpace,
    *,
    include_apps: bool = True,
    include_bases: bool = True,
    include_mounts: bool = True,
    workers: int = 4,
) -> SyncReport:
    """Clone every missing component repo. Parallel by default.

    Args:
        resolved: output of :func:`cupli.core.loader.load_space`.
        include_apps: include declared apps in the sync set.
        include_bases: include declared bases in the sync set.
        include_mounts: include declared mounts in the sync set.
        workers: maximum number of concurrent git clones.

    Returns:
        :class:`SyncReport` recording what was cloned, skipped, or failed.
    """
    targets = _collect_sync_targets(
        resolved,
        include_apps=include_apps,
        include_bases=include_bases,
        include_mounts=include_mounts,
    )
    report = SyncReport()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_clone_one, target): target for target in targets}
        for future in as_completed(futures):
            target = futures[future]
            _record_sync_outcome(future, target, report)
    return report


def _record_sync_outcome(future, target: SyncTarget, report: SyncReport) -> None:
    """Translate a future's outcome into a row of the sync report."""
    try:
        cloned = future.result()
    except CupliError as exc:
        report.failed.append((target.name, str(exc)))
        warn(f"clone failed for {target.name}: {exc}")
        return
    if cloned:
        report.cloned.append(target.name)
    else:
        report.skipped.append(target.name)


def _collect_sync_targets(
    resolved: ResolvedSpace,
    *,
    include_apps: bool,
    include_bases: bool,
    include_mounts: bool,
) -> list[SyncTarget]:
    """Build the list of sync targets from the resolved space."""
    targets: list[SyncTarget] = []
    if include_bases:
        targets.extend(_targets_from(resolved.space.bases, resolved.bases))
    if include_apps:
        targets.extend(_targets_from(resolved.space.apps, resolved.apps))
    if include_mounts:
        targets.extend(_targets_from(resolved.space.mounts, resolved.mounts))
    return targets


def _targets_from(declared, resolved_map) -> list[SyncTarget]:
    """Build sync targets from a declared-component dict + its resolved map.

    ``repo``, ``branch`` and ``post_clone`` may carry ``${VAR}`` references
    (``${SPACE_PATH}`` is common for self-hosted file:// URLs). Substitution
    runs here so the resulting strings are ready to hand to ``git`` /
    ``subprocess``.
    """
    from cupli.core.env_resolver import substitute

    out: list[SyncTarget] = []
    for name, component in declared.items():
        if not component.repo:
            continue
        scope = resolved_map[name].vars
        out.append(
            SyncTarget(
                name=name,
                path=resolved_map[name].path,
                repo=substitute(component.repo, scope),
                branch=substitute(component.branch, scope) if component.branch else None,
                post_clone=substitute(component.post_clone, scope) if component.post_clone else None,
                init_vars=dict(component.init_vars),
            ),
        )
    return out


def _clone_one(target: SyncTarget) -> bool:
    """Clone ``target.repo`` into ``target.path``. Skip if already a git repo."""
    if git.is_git_repo(target.path):
        debug(f"skip {target.name}: already a git repo")
        return False

    env = dict(os.environ)
    env.update(target.init_vars)
    suffix = f" (branch {target.branch})" if target.branch else ""
    info(f"cloning {target.name} -> {target.path}{suffix}")
    target.path.parent.mkdir(parents=True, exist_ok=True)
    git.clone_repo(target.repo, target.path, branch=target.branch, env=env)

    if target.post_clone:
        info(f"post_clone for {target.name}: {target.post_clone}")
        run_command(target.post_clone, cwd=target.path, env=env)
    return True


# --- doctor ----------------------------------------------------------------


@dataclass
class DoctorReport:
    """Aggregate result of :func:`doctor_space`."""

    ok: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def doctor_space(resolved: ResolvedSpace) -> DoctorReport:
    """Walk the resolved space and emit a structured health report."""
    report = DoctorReport()
    _check_components(report, "app", resolved.space.apps, resolved.apps)
    _check_components(report, "base", resolved.space.bases, resolved.bases)
    _check_components(report, "mount", resolved.space.mounts, resolved.mounts)
    return report


def _check_components(
    report: DoctorReport,
    kind: str,
    declared,
    resolved_map,
) -> None:
    """Append doctor rows for each declared component."""
    for name, component in declared.items():
        path = resolved_map[name].path
        label = f"{kind} {name}"
        if component.repo and not git.is_git_repo(path):
            report.warnings.append(f"{label}: repo declared but not cloned at {path}")
        elif not path.exists():
            report.warnings.append(f"{label}: path missing at {path}")
        else:
            report.ok.append(f"{label}: {path}")


__all__ = (
    "DoctorReport",
    "ScaffoldResult",
    "SyncReport",
    "SyncTarget",
    "doctor_space",
    "scaffold_space",
    "sync_space",
)
