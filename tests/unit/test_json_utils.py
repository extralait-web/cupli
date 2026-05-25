"""Tests for :mod:`cupli.utils.json`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cupli.utils.json import CupliJsonEncoder


def test_encoder_stringifies_path() -> None:
    """A bare :class:`Path` is serialised as ``str(path)`` for the host platform."""
    target = Path("/tmp") / "cupli"
    body = json.dumps({"where": target}, cls=CupliJsonEncoder)
    assert json.loads(body) == {"where": str(target)}


def test_encoder_serialises_nested_paths() -> None:
    """Paths nested inside lists and dicts also round-trip."""
    roots = [Path("/a"), Path("/b")]
    active = Path("/c")
    body = json.dumps({"roots": roots, "active": active}, cls=CupliJsonEncoder)
    assert json.loads(body) == {"roots": [str(p) for p in roots], "active": str(active)}


def test_encoder_delegates_unsupported_types() -> None:
    """Non-Path objects fall through to the base encoder, which raises."""

    class _Opaque:
        pass

    with pytest.raises(TypeError):
        json.dumps(_Opaque(), cls=CupliJsonEncoder)
