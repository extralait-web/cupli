"""Tests for :mod:`cupli.utils.lock`."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from cupli.domain.errors import CupliError
from cupli.utils.lock import acquire

if TYPE_CHECKING:
    from pathlib import Path


def test_acquire_writes_pid_and_clears_on_exit(tmp_path: Path) -> None:
    """The lockfile is created with our PID inside and removed on exit."""
    lock_path = tmp_path / "lock"
    with acquire(lock_path, space_name="demo"):
        assert lock_path.exists()
        assert lock_path.read_text() == str(os.getpid())
    assert not lock_path.exists()


def test_acquire_raises_when_lock_held_by_live_process(tmp_path: Path) -> None:
    """A lockfile owned by a live process triggers ``E027``."""
    lock_path = tmp_path / "lock"
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    with pytest.raises(CupliError) as exc_info, acquire(lock_path, space_name="demo"):
        pass
    assert exc_info.value.code == "E027"


def test_acquire_reclaims_stale_lock(tmp_path: Path) -> None:
    """A lockfile owned by a dead pid is reclaimed silently."""
    lock_path = tmp_path / "lock"
    lock_path.write_text("999999999", encoding="utf-8")
    with acquire(lock_path, space_name="demo"):
        assert lock_path.read_text() == str(os.getpid())


def test_acquire_creates_parent_directories(tmp_path: Path) -> None:
    """The lockfile's parents are created on demand."""
    lock_path = tmp_path / "nested" / "deep" / "lock"
    with acquire(lock_path, space_name="demo"):
        assert lock_path.parent.is_dir()
