"""Tests for :mod:`cupli.utils.fuzzy`."""

from __future__ import annotations

from cupli.utils.fuzzy import suggest


def test_suggest_finds_close_match() -> None:
    """A 1-char typo resolves to the canonical command."""
    assert suggest("strt", ["start", "stop", "destroy"]) == ["start"]


def test_suggest_returns_empty_for_no_match() -> None:
    """Far-off tokens return an empty list."""
    assert suggest("zzzzz", ["start", "stop"]) == []


def test_suggest_respects_n_limit() -> None:
    """``n`` caps the number of suggestions."""
    out = suggest("co", ["compose", "config", "container", "command"], n=2)
    assert len(out) <= 2


def test_suggest_respects_cutoff() -> None:
    """A higher cutoff filters out weak matches."""
    weak = suggest("co", ["compose"], cutoff=0.95)
    assert weak == []
