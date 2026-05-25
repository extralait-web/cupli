"""Tests for the exec/run/shell/wrap/sc commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cupli.cli.root import app
from cupli.core import registry

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.fixture()
def captured_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture the argv passed to ``compose_service.invoke``."""
    recorded: list[list[str]] = []

    def fake_invoke(plan, command_args, *, stream=True, check=True):
        recorded.append(list(command_args))

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()

    from cupli.cli import exec as exec_mod
    from cupli.cli import lifecycle

    monkeypatch.setattr(exec_mod, "invoke", fake_invoke)
    monkeypatch.setattr(lifecycle, "invoke", fake_invoke)
    return recorded


def _minimal_space(tmp_path: Path) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\napps:\n  api:\n    service:\n      image: alpine:3.20\n",
        encoding="utf-8",
    )
    return space_file


def test_exec_passes_workdir_and_argv(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli exec`` produces a compose argv with workdir and command."""
    _ = isolated_registry
    space = _minimal_space(tmp_path)
    result = runner.invoke(
        app,
        ["-f", str(space), "exec", "-c", "api", "-w", "/app", "ls"],
    )
    assert result.exit_code == 0, result.stdout
    assert captured_argv
    last = captured_argv[-1]
    assert last[:1] == ["exec"]
    assert "--workdir" in last
    assert "/app" in last
    assert last[-2:] == ["api", "ls"]


def test_run_includes_rm_by_default(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli run`` defaults to ``--rm``."""
    _ = isolated_registry
    space = _minimal_space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "run", "-c", "api", "echo", "hi"])
    assert result.exit_code == 0, result.stdout
    last = captured_argv[-1]
    assert last[0] == "run"
    assert "--rm" in last


def test_shell_invokes_bash(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli shell -c api`` runs ``exec api /bin/bash``."""
    _ = isolated_registry
    space = _minimal_space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "shell", "-c", "api"])
    assert result.exit_code == 0
    last = captured_argv[-1]
    assert last == ["exec", "api", "/bin/bash"]


def test_watch_passes_compose_watch(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli watch`` forwards to ``docker compose watch``."""
    _ = isolated_registry
    space = _minimal_space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "watch"])
    assert result.exit_code == 0
    last = captured_argv[-1]
    assert last[0] == "watch"


def test_upgrade_config_is_a_stub(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """``cupli upgrade-config`` reports a no-op for schema_version 1."""
    _ = isolated_registry
    space = _minimal_space(tmp_path)
    result = runner.invoke(app, ["-f", str(space), "upgrade-config"])
    assert result.exit_code == 0
    assert "schema_version 1" in result.stdout


def test_completion_install_invokes_subprocess(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cupli completion install --shell bash`` calls typer's installer subprocess."""
    import subprocess

    called: list[list[str]] = []

    def fake_run(args, check=False, **_kwargs):
        called.append(list(args))

        class _Done:
            returncode = 0

        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = runner.invoke(app, ["completion", "install", "--shell", "bash"])
    assert result.exit_code == 0, result.stdout
    assert called and "--install-completion" in called[-1]
    assert called[-1][-1] == "bash"


def test_completion_show_invokes_subprocess(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cupli completion show --shell zsh`` calls typer's --show-completion."""
    import subprocess

    called: list[list[str]] = []

    def fake_run(args, check=False, **_kwargs):
        called.append(list(args))

        class _Done:
            returncode = 0

        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = runner.invoke(app, ["completion", "show", "--shell", "zsh"])
    assert result.exit_code == 0
    assert called and "--show-completion" in called[-1]


def test_shortcut_runs_declared_command(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    captured_argv: list[list[str]],
) -> None:
    """``cupli sc <name>`` expands the declared ``commands[<name>]`` entry."""
    _ = isolated_registry
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        (
            "name: demo\napps:\n  api:\n    service:\n      image: alpine:3.20\n"
            "commands:\n  lint:\n    container: api\n    run: ruff check .\n"
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "lint"])
    assert result.exit_code == 0
    last = captured_argv[-1]
    assert last[:1] == ["exec"]
    # ``run`` is a shell command line, so cupli wraps it in ``sh -c`` to keep
    # operators (``&&``, ``|``, redirects, ``$VAR``) honest inside the container.
    assert last[-3:] == ["sh", "-c", "ruff check ."]


def test_shortcut_unknown_name_suggests_close_match(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
) -> None:
    """An unknown shortcut name surfaces a 'did you mean' suggestion."""
    _ = isolated_registry
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        (
            "name: demo\napps:\n  api:\n    service:\n      image: alpine:3.20\n"
            "commands:\n  lint:\n    container: api\n    run: ruff check .\n"
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "lnt"])
    assert result.exit_code == 1
    assert "did you mean" in result.stdout
