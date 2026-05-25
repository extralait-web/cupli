"""End-to-end lifecycle tests against a real docker daemon.

Skipped automatically when ``docker`` is not on PATH or ``docker info``
fails. Run via ``make smoke`` (or ``pytest -m docker``).
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cupli.cli.root import app
from cupli.core import registry

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.docker


def _docker_is_up() -> bool:
    """Return True when ``docker info`` succeeds, False otherwise."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _docker_is_up(), reason="docker daemon not reachable"),
]


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the registry to a per-test file."""
    registry_path = tmp_path / "spaces.json"
    monkeypatch.setattr(registry, "spaces_registry_path", lambda: registry_path)
    return registry_path


@pytest.fixture()
def runner() -> CliRunner:
    """Fresh CliRunner per test."""
    return CliRunner()


def _build_tiny_space(tmp_path: Path) -> Path:
    """Scaffold a tiny space with one alpine service and an inline compose file."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        (f"name: cupli-smoke\napps:\n  alpine:\n    composes: [{tmp_path / 'docker-compose.yml'}]\n"),
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text(
        ("services:\n  alpine:\n    image: alpine:3.20\n    command: ['sh', '-c', 'sleep 60']\n"),
        encoding="utf-8",
    )
    return space_file


def test_up_ps_down_round_trip(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli start`` boots the service; ``cupli ps`` succeeds; ``destroy`` tears down."""
    _ = isolated_registry
    space_file = _build_tiny_space(tmp_path)

    try:
        up_result = runner.invoke(app, ["-f", str(space_file), "up", "-d"])
        assert up_result.exit_code == 0, up_result.stdout

        # cupli ps streams output to the real stdout (not CliRunner's buffer);
        # verify success via direct docker query.
        ps = runner.invoke(app, ["-f", str(space_file), "ps"])
        assert ps.exit_code == 0
        listed = subprocess.run(
            ["docker", "compose", "--project-name", "cupli-smoke", "ps", "--quiet"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert listed.stdout.strip(), "docker compose ps returned no running containers"
    finally:
        runner.invoke(app, ["-f", str(space_file), "down", "-v"])


def test_exec_inside_running_container(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli exec -c alpine echo hello`` succeeds against a running service."""
    _ = isolated_registry
    space_file = _build_tiny_space(tmp_path)

    try:
        runner.invoke(app, ["-f", str(space_file), "up", "-d"])
        result = runner.invoke(
            app,
            ["-f", str(space_file), "exec", "-c", "alpine", "echo", "hello"],
        )
        assert result.exit_code == 0, result.stdout
    finally:
        runner.invoke(app, ["-f", str(space_file), "down", "-v"])
