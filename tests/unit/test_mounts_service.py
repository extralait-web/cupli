"""Tests for :mod:`cupli.services.mounts_service`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cupli.core.loader import load_space
from cupli.domain.errors import CupliError
from cupli.services.mounts_service import active_mounts, attach, detach, list_mounts

if TYPE_CHECKING:
    from pathlib import Path


def _write_space(tmp_path: Path) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        ("name: demo\napps:\n  api: {}\nmounts:\n  sdk:\n    hosted_in: [api]\n    exec_path: /opt/sdk\n"),
        encoding="utf-8",
    )
    return space_file


def test_list_mounts_returns_declared_rows(tmp_path: Path) -> None:
    """``list_mounts`` produces one row per declared mount."""
    resolved = load_space(_write_space(tmp_path))
    rows = list_mounts(resolved)
    assert len(rows) == 1
    sdk = rows[0]
    assert sdk.name == "sdk"
    assert sdk.exec_path == "/opt/sdk"
    assert sdk.hosted_in == ("api",)
    assert sdk.active is True
    assert sdk.cloned is False


def test_attach_then_detach_flips_active_state(tmp_path: Path) -> None:
    """``detach`` removes a mount from the active set; ``attach`` adds it back."""
    resolved = load_space(_write_space(tmp_path))
    assert "sdk" in active_mounts(resolved)
    detach(resolved, "sdk")
    assert "sdk" not in active_mounts(resolved)
    attach(resolved, "sdk")
    assert "sdk" in active_mounts(resolved)


def test_attach_unknown_raises_e020(tmp_path: Path) -> None:
    """``attach`` on an unknown mount raises ``E020``."""
    resolved = load_space(_write_space(tmp_path))
    with pytest.raises(CupliError) as exc_info:
        attach(resolved, "ghost")
    assert exc_info.value.code == "E020"


def test_detach_unknown_raises_e020(tmp_path: Path) -> None:
    """``detach`` on an unknown mount raises ``E020``."""
    resolved = load_space(_write_space(tmp_path))
    with pytest.raises(CupliError) as exc_info:
        detach(resolved, "ghost")
    assert exc_info.value.code == "E020"


def test_detach_excludes_mount_from_override_post(tmp_path: Path) -> None:
    """A detached mount disappears from the generated docker-compose.post.yml."""
    import yaml

    from cupli.services.compose_service import render_overrides

    resolved = load_space(_write_space(tmp_path))
    detach(resolved, "sdk")
    _, post_path, _ = render_overrides(resolved)
    data = yaml.safe_load(post_path.read_text())
    assert "services" not in data or "api" not in data.get("services", {})
