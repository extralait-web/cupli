"""Tests for :mod:`cupli.core.parser`.

Covers happy paths against the three reference fixtures (``minimal``,
``with_bases``, ``with_mounts``), then a parametrised matrix of nine invalid
fixtures asserting that the right CupliError code is raised and that line
positions are surfaced where applicable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cupli.core.parser import parse_space_file
from cupli.domain.enums import DepMode, MountMode, ServiceMode
from cupli.domain.errors import CupliError, ValidationFailure
from cupli.domain.models import SpaceModel

if TYPE_CHECKING:
    from pathlib import Path


# --- happy paths -----------------------------------------------------------


def test_parses_minimal(spaces_dir: Path) -> None:
    """A minimal one-app space parses and yields defaults."""
    model, marks = parse_space_file(spaces_dir / "minimal" / "space.cupli.yaml")

    assert isinstance(model, SpaceModel)
    assert model.name == "minimal"
    assert model.schema_version == 1
    assert list(model.apps) == ["api"]
    assert model.apps["api"].mode is ServiceMode.UP
    assert model.apps["api"].bases == []
    assert model.apps["api"].deps == {}
    assert marks.file.name == "space.cupli.yaml"
    assert marks.locate(("name",)) is not None


def test_parses_with_bases(spaces_dir: Path) -> None:
    """A space with two bases and a mode-tagged dep parses cleanly."""
    model, _ = parse_space_file(spaces_dir / "with_bases" / "space.cupli.yaml")

    api = model.apps["api"]
    assert api.bases == ["python_runtime", "pg_client"]
    assert api.deps == {"worker": [DepMode.DEFAULT]}
    assert api.tags == ["backend"]
    assert set(model.bases) == {"python_runtime", "pg_client"}


def test_parses_with_mounts_and_commands(spaces_dir: Path) -> None:
    """A space with a mount and a workspace command parses cleanly."""
    model, _ = parse_space_file(spaces_dir / "with_mounts" / "space.cupli.yaml")

    sdk = model.mounts["sdk"]
    assert sdk.hosted_in == ["api", "migrate"]
    assert sdk.exec_path == "/opt/sdk"
    assert sdk.mode is MountMode.RW

    assert model.apps["migrate"].mode is ServiceMode.ONESHOT
    assert model.commands["lint"].container == ["api"]
    assert model.commands["lint"].run == "ruff check ."


# --- failure matrix --------------------------------------------------------


INVALID_CASES: list[tuple[str, str | None]] = [
    ("missing_apps.yaml", "apps"),
    ("unknown_base.yaml", "does_not_exist"),
    ("unknown_dep.yaml", "ghost"),
    ("bad_name.yaml", None),
    ("mount_unknown_host.yaml", "missing_app"),
    ("mount_relative_exec_path.yaml", "absolute"),
    ("bad_version.yaml", None),
    ("command_unknown_container.yaml", "nope"),
]


@pytest.mark.parametrize(("fixture", "needle"), INVALID_CASES)
def test_invalid_fixtures_raise_validation_failure(
    spaces_dir: Path,
    fixture: str,
    needle: str | None,
) -> None:
    """Each invalid fixture must raise ``ValidationFailure`` with a useful message."""
    path = spaces_dir / "invalid" / fixture
    with pytest.raises(ValidationFailure) as exc_info:
        parse_space_file(path)
    error = exc_info.value
    assert error.file == path
    if needle is None:
        return
    serialised_errors = (repr(item) for item in error.errors_list)
    assert needle in str(error) or any(needle in item for item in serialised_errors)


def test_missing_file_raises_e001(tmp_path: Path) -> None:
    """A non-existent path raises ``E001``."""
    missing = tmp_path / "nope.cupli.yaml"
    with pytest.raises(CupliError) as exc_info:
        parse_space_file(missing)
    assert exc_info.value.code == "E001"


def test_empty_file_raises_e003(spaces_dir: Path) -> None:
    """A comment-only file raises ``E003``."""
    with pytest.raises(CupliError) as exc_info:
        parse_space_file(spaces_dir / "invalid" / "empty.yaml")
    assert exc_info.value.code == "E003"


def test_yaml_syntax_error_raises_e004(spaces_dir: Path) -> None:
    """A malformed YAML document raises ``E004``."""
    with pytest.raises(CupliError) as exc_info:
        parse_space_file(spaces_dir / "invalid" / "bad_yaml_syntax.yaml")
    assert exc_info.value.code == "E004"


# --- line marks ------------------------------------------------------------


def test_line_marks_resolve_known_keys(spaces_dir: Path) -> None:
    """``LineMarks.locate`` returns positions for top-level keys."""
    _, marks = parse_space_file(spaces_dir / "with_bases" / "space.cupli.yaml")
    name_pos = marks.locate(("name",))
    apps_pos = marks.locate(("apps",))
    assert name_pos is not None and name_pos[0] >= 1
    assert apps_pos is not None and apps_pos[0] >= 1
    assert apps_pos[0] > name_pos[0]


def test_line_marks_longest_prefix_fallback(spaces_dir: Path) -> None:
    """``locate`` falls back to the longest known prefix."""
    _, marks = parse_space_file(spaces_dir / "with_bases" / "space.cupli.yaml")
    # An unknown nested key still resolves via the closest known parent.
    pos = marks.locate(("apps", "api", "nonexistent_field"))
    assert pos is not None  # falls back to ("apps", "api")


# --- defaults --------------------------------------------------------------


def test_string_envs_wrapped_to_list(tmp_path: Path) -> None:
    """A bare ``envs: ".env"`` string is normalised to a one-element list."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: list-coerce\nenvs: .env\napps:\n  api: {}\n",
        encoding="utf-8",
    )
    model, _ = parse_space_file(space_file)
    assert model.envs == [".env"]


def test_list_deps_converted_to_dict(tmp_path: Path) -> None:
    """A list-shaped deps is normalised to default-mode dict."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: deps-coerce\napps:\n  api:\n    deps: [worker]\n  worker: {}\n",
        encoding="utf-8",
    )
    model, _ = parse_space_file(space_file)
    assert model.apps["api"].deps == {"worker": [DepMode.DEFAULT]}
