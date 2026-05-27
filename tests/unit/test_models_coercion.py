"""Verify that list-valued fields accept a bare string and wrap it into a one-element list.

This is the cupli convention — a one-element list is awkward in YAML, so
``tags: backend`` is equivalent to ``tags: [backend]``. The
:func:`cupli.domain.models._wrap_str_as_list` ``BeforeValidator`` does the
coercion and the JSON schema mirrors it via ``anyOf: [{string}, {array}]``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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


def test_space_accepts_top_level_volumes_secrets_configs() -> None:
    """``volumes`` / ``secrets`` / ``configs`` are accepted as compose-spec maps."""
    space = SpaceModel.model_validate(
        {
            "name": "demo",
            "apps": {"api": {}},
            "volumes": {"minio_data": {"driver": "local"}},
            "secrets": {"ci_token": {"environment": "CI_JOB_TOKEN"}},
            "configs": {"app_cfg": {"file": "./cfg.yml"}},
        },
    )
    assert space.volumes["minio_data"] == {"driver": "local"}
    assert space.secrets["ci_token"] == {"environment": "CI_JOB_TOKEN"}
    assert space.configs["app_cfg"] == {"file": "./cfg.yml"}


def test_top_level_block_null_body_coerced_to_empty_dict() -> None:
    """A named volume with no body (``minio_data:``) coerces to an empty dict."""
    space = SpaceModel.model_validate(
        {"name": "demo", "apps": {"api": {}}, "volumes": {"minio_data": None}},
    )
    assert space.volumes == {"minio_data": {}}


def test_top_level_block_non_dict_value_rejected() -> None:
    """A non-mapping block value raises a validation error (coercer passes it through)."""
    with pytest.raises(ValidationError):
        SpaceModel.model_validate(
            {"name": "demo", "apps": {"api": {}}, "volumes": {"minio_data": ["x"]}},
        )


def _command(cmd: dict) -> dict:
    return {"name": "demo", "apps": {"api": {}, "worker": {}}, "commands": {"c": cmd}}


def test_command_container_accepts_single_string() -> None:
    """``container: api`` is wrapped into a one-element list."""
    space = SpaceModel.model_validate(_command({"container": "api", "run": "x"}))
    assert space.commands["c"].container == ["api"]


def test_command_run_accepts_list_of_lines() -> None:
    """A ``run`` list is joined with newlines into a single script."""
    space = SpaceModel.model_validate(_command({"container": "api", "run": ["echo a", "echo b"]}))
    assert space.commands["c"].run == "echo a\necho b"


def test_command_args_shorthand_expands_to_required_positionals() -> None:
    """A bare list of names becomes required positional string args."""
    space = SpaceModel.model_validate(_command({"container": "api", "run": "x {{path}}", "args": ["path"]}))
    arg = space.commands["c"].args[0]
    assert arg.name == "path"
    assert arg.required is True
    assert arg.is_positional is True


def test_command_bool_arg_is_option() -> None:
    """A ``bool`` arg is treated as an option even without ``option: true``."""
    space = SpaceModel.model_validate(
        _command({"container": "api", "run": "x {{fake}}", "args": [{"name": "fake", "type": "bool"}]}),
    )
    assert space.commands["c"].args[0].is_option is True


@pytest.mark.parametrize(
    "cmd",
    [
        {"container": "api", "run": "x", "args": [{"name": "a", "required": True, "default": "z"}]},
        {"container": "api", "run": "x", "args": [{"name": "a", "short": "a"}]},
        {"container": "api", "run": "x {{b}}", "args": [{"name": "a"}]},
        {"container": "api", "run": "x", "args": [{"name": "a"}, {"name": "a"}]},
        {"container": "api", "run": "x", "args": [{"name": "a"}, {"name": "b", "required": True}]},
        {"container": "ghost", "run": "x"},
        {"container": [], "run": "x"},
        {"container": "api", "run": "x", "args": [{"name": "a-b"}]},
    ],
)
def test_command_invalid_declarations_rejected(cmd: dict) -> None:
    """Contradictory arg declarations and unknown containers are rejected."""
    with pytest.raises(ValidationError):
        SpaceModel.model_validate(_command(cmd))
