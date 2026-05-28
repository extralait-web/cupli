"""Tests for :mod:`cupli.services.mount_targets`.

The helper resolves the compose config and pre-creates host placeholders for
sub-mounts under bind targets. The compose subprocess is monkey-patched here,
so the unit tests run without docker — the assertions are about the filesystem
state created on the host.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cupli.services.mount_targets import prepare_mount_targets

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


@dataclass
class _FakePlan:
    """Minimal stand-in for :class:`CompiledPlan` — only ``project_dir`` is read."""

    project_dir: object

    # Fields touched by ``build_argv`` / ``build_env``.
    project_name: str = "demo"
    env_file: object = None
    compose_files: tuple = ()
    services: tuple = ()


def _patch_compose_config(monkeypatch: pytest.MonkeyPatch, payload: dict) -> list[list[str]]:
    """Replace ``run_command`` so the prep step reads a fixed compose config.

    Returns the list of argvs captured, so a test can assert the prep invoked
    ``docker compose config --format json``.
    """
    calls: list[list[str]] = []

    def _fake(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("cupli.services.mount_targets.run_command", _fake)
    return calls


def test_creates_dir_placeholder_for_named_volume_under_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``.venv`` (named volume) under ``/app`` (bind) gets a user-owned dir on the host."""
    bind_src = tmp_path / "src" / "back"
    bind_src.mkdir(parents=True)
    _patch_compose_config(
        monkeypatch,
        {
            "services": {
                "api": {
                    "volumes": [
                        {"type": "bind", "source": str(bind_src), "target": "/app"},
                        {"type": "volume", "source": "venv_data", "target": "/app/.venv"},
                    ],
                },
            },
        },
    )
    prepare_mount_targets(_FakePlan(project_dir=tmp_path))
    assert (bind_src / ".venv").is_dir()


def test_creates_dir_placeholder_for_cupli_mount_under_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cupli mount (bind) into ``/app/packages/lib`` gets a placeholder on the host."""
    bind_src = tmp_path / "src" / "back"
    bind_src.mkdir(parents=True)
    sdk_src = tmp_path / "src" / "mounts" / "sdk"
    sdk_src.mkdir(parents=True)
    _patch_compose_config(
        monkeypatch,
        {
            "services": {
                "api": {
                    "volumes": [
                        {"type": "bind", "source": str(bind_src), "target": "/app"},
                        {"type": "bind", "source": str(sdk_src), "target": "/app/packages/sdk"},
                    ],
                },
            },
        },
    )
    prepare_mount_targets(_FakePlan(project_dir=tmp_path))
    assert (bind_src / "packages" / "sdk").is_dir()


def test_creates_file_placeholder_for_bind_file_under_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bind whose source is a file (e.g. ``mkdocs.yml``) becomes a touched file."""
    bind_src = tmp_path / "src" / "back"
    bind_src.mkdir(parents=True)
    config_file = tmp_path / "config" / "mkdocs.yml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("site_name: demo\n", encoding="utf-8")
    _patch_compose_config(
        monkeypatch,
        {
            "services": {
                "api": {
                    "volumes": [
                        {"type": "bind", "source": str(bind_src), "target": "/app"},
                        {"type": "bind", "source": str(config_file), "target": "/app/mkdocs.yml"},
                    ],
                },
            },
        },
    )
    prepare_mount_targets(_FakePlan(project_dir=tmp_path))
    placeholder = bind_src / "mkdocs.yml"
    assert placeholder.is_file()


def test_skips_when_no_binds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service whose volumes are all named volumes leaves the host untouched."""
    _patch_compose_config(
        monkeypatch,
        {
            "services": {
                "api": {"volumes": [{"type": "volume", "source": "data", "target": "/data"}]},
            },
        },
    )
    prepare_mount_targets(_FakePlan(project_dir=tmp_path))
    # No host artefacts were created.
    assert list(tmp_path.iterdir()) == []


def test_idempotent_existing_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running twice with a target that already exists is a no-op (no error)."""
    bind_src = tmp_path / "src" / "back"
    (bind_src / ".venv").mkdir(parents=True)
    _patch_compose_config(
        monkeypatch,
        {
            "services": {
                "api": {
                    "volumes": [
                        {"type": "bind", "source": str(bind_src), "target": "/app"},
                        {"type": "volume", "source": "venv", "target": "/app/.venv"},
                    ],
                },
            },
        },
    )
    prepare_mount_targets(_FakePlan(project_dir=tmp_path))
    prepare_mount_targets(_FakePlan(project_dir=tmp_path))
    assert (bind_src / ".venv").is_dir()


def test_silent_on_compose_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing ``docker compose config`` does not raise — prep must not block."""

    def _fail(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    monkeypatch.setattr("cupli.services.mount_targets.run_command", _fail)
    # Should return cleanly, no exception.
    prepare_mount_targets(_FakePlan(project_dir=tmp_path))


def test_unrelated_target_is_not_pre_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A volume target outside any bind is left to docker compose."""
    bind_src = tmp_path / "src" / "back"
    bind_src.mkdir(parents=True)
    _patch_compose_config(
        monkeypatch,
        {
            "services": {
                "api": {
                    "volumes": [
                        {"type": "bind", "source": str(bind_src), "target": "/app"},
                        {"type": "volume", "source": "elsewhere", "target": "/var/lib/elsewhere"},
                    ],
                },
            },
        },
    )
    prepare_mount_targets(_FakePlan(project_dir=tmp_path))
    # Only /app dir on bind source exists; the /var/lib path is not under it.
    assert sorted(p.name for p in bind_src.iterdir()) == []
