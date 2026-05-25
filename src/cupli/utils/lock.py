"""File-based PID lock for per-space lifecycle invocations.

Acquires an advisory lock at ``.locals/<space>/state/lock``. Stale PIDs are
reclaimed automatically — if the owning process is no longer alive, the
lockfile is overwritten without raising.
"""

from __future__ import annotations

import os
import sys
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
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    """Windows-native liveness check.

    ``os.kill(pid, 0)`` on Windows is not a presence probe — CPython routes
    signal ``0`` to ``GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)``, which
    sends ``Ctrl+C`` to a console process group and can interrupt the
    calling process instead of returning a boolean. Probe through
    ``OpenProcess`` + ``GetExitCodeProcess`` to distinguish a live process
    from a finished one whose kernel object is still cached.
    """
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong(0)
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


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
