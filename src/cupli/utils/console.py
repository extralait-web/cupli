"""Console output and logging configured with rich.

Exposes a single module-level :class:`rich.console.Console` and short helpers
for the four severity levels cupli uses. The CLI layer wires
:func:`configure_logging` once in the root callback before any other code
emits output, plus :func:`install_excepthook` to control traceback verbosity.

The cupli house style is colour + structure with no emoji or dingbats — see
the v2 plan §0.
"""

from __future__ import annotations

import logging
import sys
import traceback
from typing import TYPE_CHECKING

import rich.console
from rich.logging import RichHandler

from cupli.domain.consts import LOGGER_NAME
from cupli.domain.enums import LogLevel

if TYPE_CHECKING:
    from types import TracebackType

console: rich.console.Console = rich.console.Console(highlight=False, soft_wrap=False)
"""Process-wide rich console used by every cupli helper."""

_logger: logging.Logger | None = None


def configure_logging(
    level: LogLevel = LogLevel.WARNING,
    *,
    no_color: bool = False,
) -> logging.Logger:
    """Initialise the cupli logger.

    Idempotent: subsequent calls return the already-configured logger
    without re-attaching handlers.

    Args:
        level: minimum severity for the cupli logger.
        no_color: when True, disable ANSI colour on the shared console.

    Returns:
        The configured cupli logger.
    """
    global _logger
    if _logger is not None:
        return _logger

    if no_color:
        console.no_color = True

    handler = RichHandler(
        console=console,
        markup=True,
        rich_tracebacks=True,
        show_time=False,
        show_path=False,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(int(level))
    logger.addHandler(handler)
    logger.propagate = False

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Return the cupli logger, configuring with defaults if necessary."""
    if _logger is None:
        return configure_logging()
    return _logger


def info(message: str) -> None:
    """Log an INFO message."""
    get_logger().info(message)


def success(message: str) -> None:
    """Log a SUCCESS-styled INFO message."""
    get_logger().info(f"[green]OK[/green] {message}")


def warn(message: str) -> None:
    """Log a WARNING message."""
    get_logger().warning(f"[yellow]WARN[/yellow] {message}")


def error(message: str) -> None:
    """Log an ERROR message."""
    get_logger().error(f"[red]ERROR[/red] {message}")


def debug(message: str) -> None:
    """Log a DEBUG message."""
    get_logger().debug(message)


def install_excepthook(*, debug_mode: bool = False) -> None:
    """Install a ``sys.excepthook`` tuned for the ``--verbose`` flag.

    Args:
        debug_mode: when True, install ``rich.traceback`` for full coloured
            tracebacks. When False, only the exception's last-line summary is
            printed plus a hint to re-run with ``--verbose``.
    """
    if debug_mode:
        _install_rich_traceback()
        return
    sys.excepthook = _terse_excepthook


def _install_rich_traceback() -> None:
    """Wire rich.traceback for debug runs."""
    from rich.traceback import install as _install

    _install(console=console, show_locals=False, width=120)


def _terse_excepthook(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    """Print the exception's last line only; hide the traceback."""
    from cupli.domain.errors import CupliError
    from cupli.utils.exceptions import print_cupli_error

    if isinstance(exc, KeyboardInterrupt):
        console.print()
        sys.exit(130)
    if isinstance(exc, CupliError):
        print_cupli_error(exc)
        sys.exit(1)
    _ = tb  # tb is the full chain; deliberately not rendered
    summary = "".join(traceback.format_exception_only(exc_type, exc)).rstrip()
    console.print(f"[red bold]error:[/red bold] [red]{summary}[/red]")
    console.print("[dim]Pass --verbose for the full traceback.[/dim]")
    sys.exit(1)


__all__ = (
    "configure_logging",
    "console",
    "debug",
    "error",
    "get_logger",
    "info",
    "install_excepthook",
    "success",
    "warn",
)
