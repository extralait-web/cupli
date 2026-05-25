"""Mount lifecycle use cases.

A mount is "active" when its volume entries appear in the generated
``docker-compose.post.yml``. By default every declared mount is active. ``cupli
mounts detach <name>`` flips it off (the next compose render omits its
volumes); ``cupli mounts attach <name>`` flips it back on. The state lives
in ``.locals/<space>/state/active-mounts.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cupli.domain.consts import STATE_DIR
from cupli.domain.errors import CupliError
from cupli.utils.git import is_git_repo
from cupli.utils.path import create_dir, read_json, write_json

if TYPE_CHECKING:
    from pathlib import Path

    from cupli.core.loader import ResolvedSpace

ACTIVE_MOUNTS_FILE = "active-mounts.json"
"""State file recording which mounts are currently active."""


@dataclass(frozen=True)
class MountInfo:
    """A row returned by :func:`list_mounts` for display."""

    name: str
    host_path: Path
    exec_path: str
    hosted_in: tuple[str, ...]
    mode: str
    active: bool
    cloned: bool


def list_mounts(resolved: ResolvedSpace) -> list[MountInfo]:
    """Build display rows for every declared mount."""
    active = active_mounts(resolved)
    return [
        MountInfo(
            name=name,
            host_path=resolved.mounts[name].path,
            exec_path=resolved.mounts[name].vars["MOUNT_EXEC_PATH"],
            hosted_in=tuple(mount.hosted_in),
            mode=mount.mode.value,
            active=name in active,
            cloned=is_git_repo(resolved.mounts[name].path),
        )
        for name, mount in resolved.space.mounts.items()
    ]


def attach(resolved: ResolvedSpace, name: str) -> None:
    """Mark ``name`` as active. Raises ``E020`` when the mount is unknown."""
    _require_declared(resolved, name)
    active = set(active_mounts(resolved))
    if name in active:
        return
    active.add(name)
    _save(_state_path(resolved), active)


def detach(resolved: ResolvedSpace, name: str) -> None:
    """Mark ``name`` as inactive. Raises ``E020`` when the mount is unknown."""
    _require_declared(resolved, name)
    active = set(active_mounts(resolved))
    if name not in active:
        return
    active.discard(name)
    _save(_state_path(resolved), active)


def active_mounts(resolved: ResolvedSpace) -> set[str]:
    """Return the set of active mount names (defaults to every declared mount)."""
    declared = set(resolved.space.mounts)
    state_path = _state_path(resolved)
    if not state_path.exists():
        return declared
    raw = read_json(state_path)
    if not isinstance(raw, list):
        return declared
    return declared & set(raw)


# --- helpers ---------------------------------------------------------------


def _require_declared(resolved: ResolvedSpace, name: str) -> None:
    """Raise ``E020`` when ``name`` is not a declared mount."""
    if name not in resolved.space.mounts:
        raise CupliError("E020", name=name)


def _state_path(resolved: ResolvedSpace) -> Path:
    """Return the absolute path of the active-mounts state file."""
    from pathlib import Path as _Path

    locals_path = resolved.space_vars["LOCALS_PATH"]
    state_dir = _Path(locals_path) / resolved.space.name / STATE_DIR
    create_dir(state_dir)
    return state_dir / ACTIVE_MOUNTS_FILE


def _save(path: Path, active: set[str]) -> None:
    """Persist the active set as a sorted JSON list."""
    write_json(path, sorted(active))


__all__ = (
    "ACTIVE_MOUNTS_FILE",
    "MountInfo",
    "active_mounts",
    "attach",
    "detach",
    "list_mounts",
)
