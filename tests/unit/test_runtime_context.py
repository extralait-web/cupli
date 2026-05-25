"""Tests for :mod:`cupli.domain.runtime`."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from cupli.domain.enums import LogLevel
from cupli.domain.runtime import RuntimeContext

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(tmp_path: Path, **overrides: object) -> RuntimeContext:
    base: dict[str, object] = {
        "space_path": tmp_path / "space.cupli.yaml",
        "space_dir": tmp_path,
        "state_dir": tmp_path / ".locals" / "demo" / "state",
    }
    base.update(overrides)
    return RuntimeContext(**base)  # type: ignore[arg-type]


def test_defaults_applied(tmp_path: Path) -> None:
    """Optional flags pick up their declared defaults."""
    ctx = _ctx(tmp_path)
    assert ctx.log_level is LogLevel.WARNING
    assert ctx.strict_vars is False
    assert ctx.allow_shadow is False
    assert ctx.no_color is False
    assert ctx.time_profile is False
    assert isinstance(ctx.now, datetime)


def test_required_paths_validated(tmp_path: Path) -> None:
    """Missing path fields raise pydantic ``ValidationError``."""
    with pytest.raises(ValidationError):
        RuntimeContext(  # type: ignore[call-arg]
            space_path=tmp_path / "space.cupli.yaml",
            space_dir=tmp_path,
        )


def test_context_is_frozen(tmp_path: Path) -> None:
    """``frozen=True`` blocks attribute assignment."""
    ctx = _ctx(tmp_path)
    with pytest.raises(ValidationError):
        ctx.strict_vars = True  # type: ignore[misc]


def test_extra_fields_rejected(tmp_path: Path) -> None:
    """``extra='forbid'`` rejects unknown keyword arguments."""
    with pytest.raises(ValidationError):
        _ctx(tmp_path, unexpected="oops")


def test_explicit_overrides_take_precedence(tmp_path: Path) -> None:
    """Explicit kwargs override the defaults."""
    fixed = datetime(2026, 1, 1, 12, 0, 0)
    ctx = _ctx(
        tmp_path,
        log_level=LogLevel.DEBUG,
        strict_vars=True,
        allow_shadow=True,
        no_color=True,
        time_profile=True,
        now=fixed,
    )
    assert ctx.log_level is LogLevel.DEBUG
    assert ctx.strict_vars is True
    assert ctx.allow_shadow is True
    assert ctx.no_color is True
    assert ctx.time_profile is True
    assert ctx.now == fixed
