"""Tests for :mod:`cupli.utils.subprocess`."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from cupli.utils.subprocess import run_command

if TYPE_CHECKING:
    from pathlib import Path


def test_run_command_returns_completed_process() -> None:
    """``run_command`` returns a ``CompletedProcess`` with text output."""
    result = run_command([sys.executable, "-c", "print('hi')"], stream=False)
    assert result.returncode == 0
    assert result.stdout.strip() == "hi"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="shlex.split treats backslashes in C:\\... as escapes, which breaks the cross-platform check",
)
def test_run_command_accepts_shell_string() -> None:
    """A string argv is split with ``shlex``."""
    result = run_command(f"{sys.executable} -c 'print(42)'", stream=False)
    assert result.stdout.strip() == "42"


def test_run_command_propagates_env() -> None:
    """Extra env entries are visible to the child."""
    code = 'import os; print(os.environ["CUPLI_TEST_VAR"])'
    result = run_command(
        [sys.executable, "-c", code],
        env={"CUPLI_TEST_VAR": "from-test"},
        stream=False,
    )
    assert result.stdout.strip() == "from-test"


def test_run_command_uses_cwd(tmp_path: Path) -> None:
    """``cwd`` switches the child's working directory."""
    sub = tmp_path / "sub"
    sub.mkdir()
    result = run_command(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=sub,
        stream=False,
    )
    assert result.stdout.strip().endswith("sub")


def test_run_command_raises_on_nonzero_when_check_true() -> None:
    """A non-zero exit raises ``CalledProcessError`` by default."""
    with pytest.raises(subprocess.CalledProcessError):
        run_command([sys.executable, "-c", "raise SystemExit(2)"], stream=False)


def test_run_command_swallows_nonzero_when_check_false() -> None:
    """``check=False`` returns the failed process without raising."""
    result = run_command(
        [sys.executable, "-c", "raise SystemExit(3)"],
        stream=False,
        check=False,
    )
    assert result.returncode == 3
