"""Validation tests for ``host_bridge`` and ``exports`` schema additions."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from cupli.domain.enums import ExportStrategy, RefreshHook
from cupli.domain.models import HostBridgeSpec, SpaceModel


def _model(text: str) -> SpaceModel:
    return SpaceModel.model_validate(yaml.safe_load(text))


def test_host_bridge_bool_true_enables_with_defaults() -> None:
    """``host_bridge: true`` enables bridging with default spec."""
    space = _model(
        "name: demo\napps:\n  web: {}\nmounts:\n  ui:\n    hosted_in: [web]\n    exec_path: /app/x\n    host_bridge: true\n"
    )
    mount = space.mounts["ui"]
    assert mount.bridge_enabled is True
    assert mount.bridge_spec == HostBridgeSpec()


def test_host_bridge_mapping_overrides() -> None:
    """A mapping ``host_bridge`` parses into a :class:`HostBridgeSpec`."""
    space = _model(
        "name: demo\napps:\n  web: {}\nmounts:\n  ui:\n    hosted_in: [web]\n    exec_path: /app/x\n"
        "    host_bridge:\n      link: /custom/link\n      relative: false\n"
    )
    spec = space.mounts["ui"].bridge_spec
    assert spec.link == "/custom/link"
    assert spec.relative is False


def test_host_bridge_default_off() -> None:
    """Without ``host_bridge`` a mount is not bridged."""
    space = _model("name: demo\napps:\n  web: {}\nmounts:\n  ui:\n    hosted_in: [web]\n    exec_path: /app/x\n")
    assert space.mounts["ui"].bridge_enabled is False


def test_export_defaults() -> None:
    """An export defaults to ``sync`` + ``refresh_on: [build]`` + gitignore."""
    space = _model(
        "name: demo\napps:\n  web: {}\nexports:\n  nm:\n    from: web\n    exec_path: /app/node_modules\n    path: /h/nm\n"
    )
    export = space.exports["nm"]
    assert export.from_app == "web"
    assert export.strategy is ExportStrategy.SYNC
    assert export.refresh_on == [RefreshHook.BUILD]
    assert export.gitignore is True


def test_export_refresh_on_accepts_bare_string() -> None:
    """``refresh_on: up`` is wrapped into a one-element list."""
    space = _model(
        "name: demo\napps:\n  web: {}\nexports:\n  nm:\n    from: web\n    exec_path: /app/nm\n    path: /h\n"
        "    refresh_on: up\n"
    )
    assert space.exports["nm"].refresh_on == [RefreshHook.UP]


def test_export_unknown_from_app_rejected() -> None:
    """An export referencing an undeclared ``from`` app fails validation."""
    with pytest.raises(ValidationError) as exc:
        _model("name: demo\napps:\n  web: {}\nexports:\n  nm:\n    from: ghost\n    exec_path: /app/nm\n    path: /h\n")
    assert "ghost" in str(exc.value)


def test_export_relative_exec_path_rejected() -> None:
    """A non-absolute ``exec_path`` fails validation."""
    with pytest.raises(ValidationError):
        _model("name: demo\napps:\n  web: {}\nexports:\n  nm:\n    from: web\n    exec_path: rel/path\n    path: /h\n")
