"""Tests for :mod:`cupli.core.loader`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cupli.core.loader import COMPONENT_RESERVED, SPACE_RESERVED, load_space
from cupli.domain.errors import CupliError

if TYPE_CHECKING:
    from pathlib import Path


def _write_space(target: Path, contents: str) -> Path:
    """Write a yaml fixture and return its absolute path."""
    target.write_text(contents, encoding="utf-8")
    return target


def test_space_auto_vars_populated(tmp_path: Path) -> None:
    """``SPACE_PATH`` and the default directory paths are computed for the space."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        "name: tiny\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    assert resolved.space.name == "tiny"
    assert resolved.space_vars["SPACE_NAME"] == "tiny"
    assert resolved.space_vars["SPACE_PATH"] == str(tmp_path.resolve())
    assert resolved.space_vars["APPS_PATH"].endswith("/apps")
    assert resolved.space_vars["BASES_PATH"].endswith("/bases")
    assert resolved.space_vars["MOUNTS_PATH"].endswith("/mounts")
    assert resolved.space_vars["LOCALS_PATH"].endswith("/.locals")
    assert resolved.space_vars["NETWORK"] == "tiny"
    assert resolved.space_vars["COMPOSE_PROJECT_NAME"] == "tiny"


def test_app_path_defaults_to_apps_dir(tmp_path: Path) -> None:
    """An app without explicit ``path`` is anchored under ``APPS_PATH``."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        "name: tiny\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    api = resolved.apps["api"]
    assert api.path == (tmp_path / "src" / "apps" / "api").resolve()
    assert api.vars["APP_NAME"] == "api"
    assert api.vars["APP_PATH"] == str(api.path)
    assert api.vars["APP_LOCAL_PATH"].endswith("/.locals/api")


def test_app_path_uses_explicit_value(tmp_path: Path) -> None:
    """An explicit ``apps[*].path`` is honoured (after var substitution)."""
    custom = tmp_path / "checkout" / "api"
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        f"name: tiny\napps:\n  api:\n    path: {custom}\n",
    )
    resolved = load_space(space_file)
    assert resolved.apps["api"].path == custom.resolve()


def test_sibling_app_path_var_resolves_in_yaml(tmp_path: Path) -> None:
    """``${<NAME>_APP_PATH}`` resolves to the sibling's default path inside YAML."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        "name: tiny\napps:\n  backend: {}\n  celery:\n    path: ${BACKEND_APP_PATH}\n",
    )
    resolved = load_space(space_file)
    backend_default = (tmp_path / "src" / "apps" / "backend").resolve()
    assert resolved.apps["backend"].path == backend_default
    assert resolved.apps["celery"].path == backend_default


def test_mount_path_var_resolves_in_yaml(tmp_path: Path) -> None:
    """``${<NAME>_MOUNT_PATH}`` is available to apps and other mounts."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        (
            "name: tiny\n"
            "apps:\n  api:\n    vars:\n      SDK_DIR: ${SHARED_MOUNT_PATH}\n"
            "mounts:\n  shared:\n    hosted_in: [api]\n    exec_path: /opt/shared\n"
        ),
    )
    resolved = load_space(space_file)
    expected = (tmp_path / "src" / "mounts" / "shared").resolve()
    assert resolved.apps["api"].vars["SDK_DIR"] == str(expected)


def test_base_path_var_resolves_in_yaml(tmp_path: Path) -> None:
    """``${<NAME>_BASE_PATH}`` is available to apps and other components."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        ("name: tiny\nbases:\n  pyrt: {}\napps:\n  api:\n    vars:\n      BASE_DIR: ${PYRT_BASE_PATH}\n"),
    )
    resolved = load_space(space_file)
    expected = (tmp_path / "src" / "bases" / "pyrt").resolve()
    assert resolved.apps["api"].vars["BASE_DIR"] == str(expected)


def test_base_vars_merge_into_app_scope(tmp_path: Path) -> None:
    """An app inherits its bases' variables (in C3 order)."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        (
            "name: tiny\n"
            "bases:\n"
            "  py:\n"
            "    vars: {PYTHONUNBUFFERED: '1'}\n"
            "apps:\n"
            "  api:\n"
            "    bases: [py]\n"
            "    vars:\n"
            "      LOG_LEVEL: debug\n"
        ),
    )
    resolved = load_space(space_file)
    api = resolved.apps["api"]
    assert api.vars["PYTHONUNBUFFERED"] == "1"
    assert api.vars["LOG_LEVEL"] == "debug"


def test_app_vars_can_reference_outer_scope(tmp_path: Path) -> None:
    """App-scope vars may reference SPACE_*, APP_*, and base vars."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        (
            "name: tiny\n"
            "vars: {REGISTRY: 'ghcr.io/x'}\n"
            "apps:\n"
            "  api:\n"
            "    vars:\n"
            "      IMAGE: '${REGISTRY}/api:${APP_NAME}'\n"
        ),
    )
    resolved = load_space(space_file)
    assert resolved.apps["api"].vars["IMAGE"] == "ghcr.io/x/api:api"


def test_mount_paths_and_vars(tmp_path: Path) -> None:
    """Mount auto-vars cover MOUNT_NAME / MOUNT_PATH / MOUNT_EXEC_PATH."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        ("name: tiny\napps:\n  api: {}\nmounts:\n  sdk:\n    hosted_in: [api]\n    exec_path: /opt/sdk\n"),
    )
    resolved = load_space(space_file)
    sdk = resolved.mounts["sdk"]
    assert sdk.path == (tmp_path / "src" / "mounts" / "sdk").resolve()
    assert sdk.vars["MOUNT_NAME"] == "sdk"
    assert sdk.vars["MOUNT_EXEC_PATH"] == "/opt/sdk"
    assert sdk.vars["MOUNT_HOST"] == str(sdk.path)


def test_env_file_values_propagate(tmp_path: Path) -> None:
    """Values from declared env files appear in the resolved scope."""
    env_file = tmp_path / ".env"
    env_file.write_text("STACK_ENV=dev\n", encoding="utf-8")
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        "name: tiny\nenvs: [.env]\napps:\n  api: {}\n",
    )
    resolved = load_space(space_file)
    assert resolved.space_vars["STACK_ENV"] == "dev"


def test_strict_mode_raises_on_unknown_ref(tmp_path: Path) -> None:
    """An unknown ``${VAR}`` reference raises ``E016`` under ``strict_vars``."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        ("name: tiny\nvars:\n  Y: '${X}'\napps:\n  api: {}\n"),
    )
    with pytest.raises(CupliError) as exc_info:
        load_space(space_file, strict_vars=True)
    assert exc_info.value.code == "E016"


def test_user_shadowing_reserved_space_var_raises_e015(tmp_path: Path) -> None:
    """Shadowing a reserved space-scope auto-var without ``allow_shadow`` raises ``E015``."""
    space_file = _write_space(
        tmp_path / "space.cupli.yaml",
        ("name: tiny\nvars:\n  SPACE_NAME: 'overridden'\napps:\n  api: {}\n"),
    )
    with pytest.raises(CupliError) as exc_info:
        load_space(space_file)
    assert exc_info.value.code == "E015"


def test_reserved_constants_cover_documented_names() -> None:
    """The reserved sets keep documented auto-var names in sync."""
    assert "SPACE_NAME" in SPACE_RESERVED
    assert "APPS_PATH" in SPACE_RESERVED
    assert "APP_NAME" in COMPONENT_RESERVED
    assert "APP_PATH" in COMPONENT_RESERVED
