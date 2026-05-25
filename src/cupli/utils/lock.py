"""File-based PID lock for per-space lifecycle invocations.

Acquires an advisory lock at ``.locals/<space>/state/lock``. Stale PIDs are
reclaimed automatically — if the owning process is no longer alive, the
lockfile is overwritten without raising.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

from cupli.domain.errors import CupliError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _pid_alive(pid: int) -> bool:
    """Return True when ``pid`` belongs to a live process visible to this user."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@contextmanager
def acquire(lock_path: Path, *, space_name: str) -> Iterator[None]:
    """Acquire an advisory file lock for the given space.

    Args:
        lock_path: absolute path of the lockfile.
        space_name: name of the space, used in E027 messages.

    Yields:
        None while the lock is held.

    Raises:
        CupliError: ``E027`` when a live process already holds the lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        owner_pid = _read_pid(lock_path)
        if _pid_alive(owner_pid):
            raise CupliError("E027", name=space_name, pid=owner_pid)

    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass


def _read_pid(lock_path: Path) -> int:
    """Read a PID out of the lockfile; 0 on parse failure."""
    try:
        text = lock_path.read_text(encoding="utf-8").strip()
        return int(text) if text else 0
    except (OSError, ValueError):
        return 0


__all__ = ("acquire",)
