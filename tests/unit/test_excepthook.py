"""Tests for the terse vs. verbose traceback hook."""

from __future__ import annotations

import sys

import pytest

from cupli.utils.console import install_excepthook


@pytest.fixture(autouse=True)
def restore_excepthook() -> None:
    """Restore the original ``sys.excepthook`` after every test."""
    saved = sys.excepthook
    yield
    sys.excepthook = saved


def test_terse_hook_prints_only_summary_and_exits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without ``--verbose``, the hook prints a one-line summary and ``sys.exit(1)``."""
    install_excepthook(debug_mode=False)
    with pytest.raises(SystemExit) as exit_info:
        try:
            raise ValueError("something went wrong")
        except ValueError:
            sys.excepthook(*sys.exc_info())  # type: ignore[arg-type]
    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "ValueError" in out
    assert "something went wrong" in out
    assert "Pass --verbose" in out
    # No file paths from a traceback frame leaked into the terse output.
    assert "Traceback" not in out


def test_terse_hook_renders_cupli_error_with_catalog(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The hook routes :class:`CupliError` through the catalog renderer."""
    from cupli.domain.errors import CupliError

    install_excepthook(debug_mode=False)
    with pytest.raises(SystemExit) as exit_info:
        try:
            raise CupliError("E001", path="/missing")
        except CupliError:
            sys.excepthook(*sys.exc_info())  # type: ignore[arg-type]
    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "E001" in out
    assert "Space file not found" in out


def test_debug_mode_installs_rich_traceback() -> None:
    """``debug_mode=True`` swaps in ``rich.traceback``'s installer."""
    install_excepthook(debug_mode=False)
    terse = sys.excepthook
    install_excepthook(debug_mode=True)
    assert sys.excepthook is not terse
