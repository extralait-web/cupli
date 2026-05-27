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


class _InvokeSpy:
    """Records ``invoke`` calls and returns per-container exit codes."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.returncodes: dict[str, int] = {}

    def __call__(self, plan, command_args, *, stream=True, check=True):
        argv = list(command_args)
        container = argv[argv.index("sh") - 1] if "sh" in argv else None
        self.calls.append({"argv": argv, "stream": stream, "container": container})
        code = self.returncodes.get(container, 0) if container else 0

        class _Done:
            returncode = code
            stdout = f"out:{container}\n"
            stderr = ""

        return _Done()

    @property
    def containers(self) -> list[str]:
        """Container targets across recorded calls, in order."""
        return [call["container"] for call in self.calls if call["container"]]


@pytest.fixture()
def invoke_spy(monkeypatch: pytest.MonkeyPatch) -> _InvokeSpy:
    """Patch ``compose_service.invoke`` with a configurable spy."""
    spy = _InvokeSpy()
    from cupli.cli import exec as exec_mod

    monkeypatch.setattr(exec_mod, "invoke", spy)
    return spy


def _multi_container_space(tmp_path: Path, body: str) -> Path:
    """Write a space with api+worker apps and the given ``commands:`` body."""
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\napps:\n"
        "  api:\n    service:\n      image: alpine:3.20\n"
        "  worker:\n    service:\n      image: alpine:3.20\n"
        f"{body}",
        encoding="utf-8",
    )
    return space_file


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


def test_shortcut_multi_container_runs_each(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """A multi-container command runs once per listed container."""
    _ = isolated_registry
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  ping:\n    container: [api, worker]\n    run: echo hi\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "ping"])
    assert result.exit_code == 0
    assert invoke_spy.containers == ["api", "worker"]


def test_shortcut_sequential_fail_fast(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """Sequential mode stops at the first non-zero exit and propagates it."""
    _ = isolated_registry
    invoke_spy.returncodes = {"api": 3}
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  ping:\n    container: [api, worker]\n    run: echo hi\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "ping"])
    assert result.exit_code == 3
    assert invoke_spy.containers == ["api"]


def test_shortcut_continue_runs_all(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """Continue mode runs every container despite a failure and aggregates."""
    _ = isolated_registry
    invoke_spy.returncodes = {"api": 5}
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  ping:\n    container: [api, worker]\n    execute: continue\n    run: echo hi\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "ping"])
    assert result.exit_code == 5
    assert invoke_spy.containers == ["api", "worker"]


def test_shortcut_parallel_uses_capture(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """Parallel mode captures output (stream=False) for each container."""
    _ = isolated_registry
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  ping:\n    container: [api, worker]\n    execute: parallel\n    run: echo hi\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "ping"])
    assert result.exit_code == 0
    assert sorted(invoke_spy.containers) == ["api", "worker"]
    assert all(call["stream"] is False for call in invoke_spy.calls)


def test_shortcut_typed_args_substituted(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """Declared args are parsed and substituted into the run line via ``{{}}``."""
    _ = isolated_registry
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  migrate:\n    container: api\n"
        "    run: migrate {{app}} {{fake}}\n"
        "    args:\n      - name: app\n        required: true\n"
        "      - name: fake\n        type: bool\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "migrate", "users", "--fake"])
    assert result.exit_code == 0
    last = invoke_spy.calls[-1]["argv"]
    assert last[-3:] == ["sh", "-c", "migrate users --fake"]


def test_shortcut_args_no_passthrough(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """With declared args no ``$@`` passthrough is appended to the snippet."""
    _ = isolated_registry
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  migrate:\n    container: api\n    run: migrate {{app}}\n"
        "    args:\n      - name: app\n        required: true\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "migrate", "users"])
    assert result.exit_code == 0
    last = invoke_spy.calls[-1]["argv"]
    assert '"$@"' not in last[-2]
    assert last[-3:] == ["sh", "-c", "migrate users"]


def test_shortcut_multiline_run(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """A multi-line ``run`` block is passed verbatim to ``sh -c``."""
    _ = isolated_registry
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  setup:\n    container: api\n    run: |\n      echo one\n      echo two\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "setup"])
    assert result.exit_code == 0
    last = invoke_spy.calls[-1]["argv"]
    assert last[-1] == "echo one\necho two"


def test_shortcut_singleline_passthrough_appends_args(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """A no-args single-line command appends extra tokens via ``"$@"``."""
    _ = isolated_registry
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  lint:\n    container: api\n    run: ruff check\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "lint", "src", "--fix"])
    assert result.exit_code == 0
    argv = invoke_spy.calls[-1]["argv"]
    tail = argv[argv.index("sh") :]
    assert tail == ["sh", "-c", 'ruff check "$@"', "_", "src", "--fix"]


def test_shortcut_multiline_passthrough_not_mangled(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    invoke_spy: _InvokeSpy,
) -> None:
    """A multi-line no-args command passes tokens positionally without appending ``"$@"``."""
    _ = isolated_registry
    space_file = _multi_container_space(
        tmp_path,
        "commands:\n  setup:\n    container: api\n    run: |\n      echo one\n      echo two\n",
    )
    result = runner.invoke(app, ["-f", str(space_file), "sc", "setup", "extra"])
    assert result.exit_code == 0
    argv = invoke_spy.calls[-1]["argv"]
    # The script is unchanged (no `"$@"` glued onto the last line); tokens still
    # arrive as positional parameters after the `_` sentinel.
    assert argv[-3:] == ["echo one\necho two", "_", "extra"]
    assert '"$@"' not in argv[-3]
