"""Tests for :mod:`cupli.core.c3`."""

from __future__ import annotations

import pytest

from cupli.core.c3 import c3_linearise
from cupli.domain.errors import CupliError
from cupli.domain.models import AppModel, BaseAppModel, SpaceModel


def _space(*, apps: dict[str, AppModel], bases: dict[str, BaseAppModel] | None = None) -> SpaceModel:
    """Helper to build a minimal SpaceModel for c3 testing."""
    return SpaceModel(name="t", apps=apps, bases=bases or {})


def test_no_bases_returns_empty_list() -> None:
    """An app without ``bases`` linearises to an empty list."""
    space = _space(apps={"api": AppModel()})
    assert c3_linearise(space, "api") == []


def test_single_base_is_returned() -> None:
    """One declared base linearises to that one base."""
    space = _space(
        apps={"api": AppModel(bases=["b1"])},
        bases={"b1": BaseAppModel()},
    )
    assert c3_linearise(space, "api") == ["b1"]


def test_multiple_bases_preserve_declaration_order() -> None:
    """Multiple flat bases preserve left-to-right declaration order."""
    space = _space(
        apps={"api": AppModel(bases=["b1", "b2", "b3"])},
        bases={
            "b1": BaseAppModel(),
            "b2": BaseAppModel(),
            "b3": BaseAppModel(),
        },
    )
    assert c3_linearise(space, "api") == ["b1", "b2", "b3"]


def test_unknown_app_raises_e010() -> None:
    """Asking for the linearisation of an unknown app raises ``E010``."""
    space = _space(apps={"api": AppModel()})
    with pytest.raises(CupliError) as exc_info:
        c3_linearise(space, "ghost")
    assert exc_info.value.code == "E010"
