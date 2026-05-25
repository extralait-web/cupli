"""Tests for :mod:`cupli.utils.exceptions` rendering of CupliError variants."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cupli.domain.errors import CupliError, ValidationFailure
from cupli.domain.plan import LineMarks
from cupli.utils.exceptions import print_cupli_error

if TYPE_CHECKING:
    from pathlib import Path


def test_print_cupli_error_renders_code_title_body_hint(capsys) -> None:
    """A plain :class:`CupliError` shows code, title, body, and hint."""
    exc = CupliError("E001", path="/no/such/file")
    print_cupli_error(exc)
    out = capsys.readouterr().out
    assert "E001" in out
    assert "Space file not found" in out
    assert "/no/such/file" in out
    assert "hint:" in out


def test_print_cupli_error_lists_validation_details(capsys, tmp_path: Path) -> None:
    """A :class:`ValidationFailure` enumerates every pydantic error."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text("name: bad\n", encoding="utf-8")
    marks = LineMarks(file=space_file, items={("apps", "bad-mode", "mode"): (6, 5)})
    exc = ValidationFailure(
        file=space_file,
        errors_list=[
            {"loc": ("apps", "bad-mode", "mode"), "msg": "Input should be 'up'"},
            {"loc": ("mounts", "no-host", "hosted_in"), "msg": "Field required"},
        ],
        marks=marks,
    )
    print_cupli_error(exc)
    out = capsys.readouterr().out
    assert "apps.bad-mode.mode" in out
    assert "Input should be 'up'" in out
    assert ":6:5" in out
    assert "mounts.no-host.hosted_in" in out
    assert "Field required" in out


def test_print_cupli_error_validation_without_marks_skips_position(
    capsys,
    tmp_path: Path,
) -> None:
    """Errors without source marks still render — just without ``file:line:col``."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text("name: bad\n", encoding="utf-8")
    exc = ValidationFailure(
        file=space_file,
        errors_list=[{"loc": ("name",), "msg": "Field required"}],
        marks=None,
    )
    print_cupli_error(exc)
    out = capsys.readouterr().out
    assert "name" in out
    assert "Field required" in out
    assert ":1:" not in out
