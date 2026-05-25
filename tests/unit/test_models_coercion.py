"""Verify that list-valued fields accept a bare string and wrap it into a one-element list.

This is the cupli convention — a one-element list is awkward in YAML, so
``tags: backend`` is equivalent to ``tags: [backend]``. The
:func:`cupli.domain.models._wrap_str_as_list` ``BeforeValidator`` does the
coercion and the JSON schema mirrors it via ``anyOf: [{string}, {array}]``.
"""

from __future__ import annotations

from cupli.domain.models import AppModel, MountModel, SpaceModel


def test_tags_accepts_single_string() -> None:
    """``apps.<name>.tags: backend`` (bare string) becomes ``["backend"]``."""
    app = AppModel.model_validate({"tags": "backend"})
    assert app.tags == ["backend"]


def test_bases_accepts_single_string() -> None:
    """``apps.<name>.bases: python_runtime`` becomes ``["python_runtime"]``."""
    app = AppModel.model_validate({"bases": "python_runtime"})
    assert app.bases == ["python_runtime"]


def test_composes_accepts_single_string() -> None:
    """``composes: ./compose.yml`` becomes ``["./compose.yml"]``."""
    app = AppModel.model_validate({"composes": "./compose.yml"})
    assert app.composes == ["./compose.yml"]


def test_ports_accepts_single_string() -> None:
    """``ports: "8000:8000"`` becomes ``["8000:8000"]``."""
    app = AppModel.model_validate({"ports": "8000:8000"})
    assert app.ports == ["8000:8000"]


def test_envs_accepts_single_string() -> None:
    """``envs: ./.env`` becomes ``["./.env"]``."""
    app = AppModel.model_validate({"envs": "./.env"})
    assert app.envs == ["./.env"]


def test_vars_accepts_yaml_null_as_empty_dict() -> None:
    """A bare ``vars:`` (YAML null) on an app is coerced to ``{}``."""
    app = AppModel.model_validate({"vars": None})
    assert app.vars == {}


def test_service_override_vars_accepts_yaml_null_as_empty_dict() -> None:
    """A bare ``vars:`` inside a ``services.<name>`` entry is coerced to ``{}``."""
    from cupli.domain.models import ServiceOverride

    override = ServiceOverride.model_validate({"vars": None})
    assert override.vars == {}


def test_mount_hosted_in_accepts_single_string() -> None:
    """``hosted_in: api`` becomes ``["api"]`` on a mount."""
    mount = MountModel.model_validate({"hosted_in": "api", "exec_path": "/opt/sdk"})
    assert mount.hosted_in == ["api"]


def test_envs_at_space_scope_accepts_single_string() -> None:
    """``envs: ./.env`` at the top level works just like at the app level."""
    space = SpaceModel.model_validate({"name": "demo", "envs": "./.env", "apps": {"api": {}}})
    assert space.envs == ["./.env"]
