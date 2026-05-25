"""Subprocess wrapper used by cupli services.

Sane defaults around :func:`subprocess.run`:

- inherits a controlled subset of the parent environment
- streams stdout/stderr live when ``stream=True``
- raises :class:`subprocess.CalledProcessError` on non-zero exit when
  ``check=True`` (callers translate it into the right :class:`CupliError`)
"""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import TYPE_CHECKING

from cupli.utils.console import debug

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


def run_command(
    argv: Sequence[str] | str,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    stream: bool = True,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess with cupli-standard configuration.

    Args:
        argv: command line as a list or single string (split with ``shlex``).
        cwd: working directory; None means caller's cwd.
        env: extra environment variables overlaid on top of ``os.environ``.
            The overlay (NOT the full inherited process env) is mirrored to
            DEBUG output, so ``cupli -v`` shows exactly what cupli injects.
        stream: when True, child stdout/stderr inherit the parent's streams;
            when False, output is captured into the returned ``CompletedProcess``.
        check: when True, raise on non-zero exit.
        timeout: optional timeout in seconds.

    Returns:
        Completed process.

    Raises:
        subprocess.CalledProcessError: when ``check=True`` and exit is non-zero.
    """
    args = shlex.split(argv) if isinstance(argv, str) else list(argv)
    final_env = dict(os.environ)
    if env is not None:
        final_env.update(env)

    debug(f"run: {shlex.join(args)}")
    if env:
        for key, value in env.items():
            debug(f"  env {key}={value}")

    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=final_env,
        check=check,
        capture_output=not stream,
        text=True,
        timeout=timeout,
    )


__all__ = ("run_command",)
