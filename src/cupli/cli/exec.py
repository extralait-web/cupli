"""``exec`` / ``run`` / ``shell`` / ``wrap`` commands.

``exec`` and ``run`` are thin proxies over ``docker compose exec`` and
``docker compose run --rm`` respectively. ``shell`` is a convenience
wrapper around ``exec`` that picks ``/bin/bash`` (or another shell via
``--shell``). ``wrap`` runs a command on the HOST while exporting the
container's resolved environment — useful for scripts that need the
service's env vars but cannot run inside docker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import click
import typer

from cupli.cli._completion import (
    complete_app_names,
    complete_service_names,
    complete_shortcut_names,
)
from cupli.cli._shortcuts import parse_extra, render_run, specs_from_models
from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.domain.consts import COMMANDS_PANEL_TITLE
from cupli.domain.enums import ExecuteMode
from cupli.domain.errors import CupliError
from cupli.services.compose_service import invoke, make_plan
from cupli.utils.exceptions import suppress_known_exceptions
from cupli.utils.subprocess import run_command

if TYPE_CHECKING:
    from subprocess import CompletedProcess

    from cupli.core.loader import ResolvedSpace
    from cupli.domain.models import CommandArg, CommandShortcut
    from cupli.services.compose_service import CompiledPlan


@suppress_known_exceptions
def exec_command(
    ctx: typer.Context,
    container: Annotated[
        str,
        typer.Option(
            "--container",
            "-c",
            help="Compose service name.",
            autocompletion=complete_service_names,
        ),
    ],
    workdir: Annotated[
        str | None, typer.Option("--workdir", "-w", help="Working directory inside the container.")
    ] = None,
    cmd: Annotated[list[str] | None, typer.Argument(help="Command to run inside the container.")] = None,
) -> None:
    """Run a command inside a running container (``docker compose exec``)."""
    resolved, plan = _build_plan(ctx)
    _ = resolved
    args = ["exec"]
    if workdir:
        args.extend(["--workdir", workdir])
    args.append(container)
    args.extend(cmd or ["bash"])
    invoke(plan, args)


@suppress_known_exceptions
def run_cli_command(
    ctx: typer.Context,
    container: Annotated[
        str,
        typer.Option(
            "--container",
            "-c",
            help="Compose service name.",
            autocompletion=complete_service_names,
        ),
    ],
    workdir: Annotated[
        str | None, typer.Option("--workdir", "-w", help="Working directory inside the container.")
    ] = None,
    keep: Annotated[bool, typer.Option("--no-rm", help="Do not pass --rm to docker compose run.")] = False,
    cmd: Annotated[list[str] | None, typer.Argument(help="Command to run inside a one-shot container.")] = None,
) -> None:
    """Start a one-shot container and run a command (``docker compose run --rm``)."""
    resolved, plan = _build_plan(ctx)
    _ = resolved
    args = ["run"]
    if not keep:
        args.append("--rm")
    if workdir:
        args.extend(["--workdir", workdir])
    args.append(container)
    args.extend(cmd or ["bash"])
    invoke(plan, args)


@suppress_known_exceptions
def shell_command(
    ctx: typer.Context,
    container: Annotated[
        str,
        typer.Option(
            "--container",
            "-c",
            help="Compose service name.",
            autocompletion=complete_service_names,
        ),
    ],
    shell: Annotated[str, typer.Option("--shell", help="Shell executable inside the container.")] = "/bin/bash",
) -> None:
    """Open an interactive shell inside the named container."""
    resolved, plan = _build_plan(ctx)
    _ = resolved
    invoke(plan, ["exec", container, shell])


@suppress_known_exceptions
def wrap_command(
    ctx: typer.Context,
    container: Annotated[
        str,
        typer.Option(
            "--container",
            "-c",
            help="App whose resolved env to export.",
            autocompletion=complete_app_names,
        ),
    ],
    cmd: Annotated[list[str] | None, typer.Argument(help="Command to run on the host.")] = None,
) -> None:
    """Run a host command with the named app's resolved environment exported."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    if container not in resolved.apps:
        raise CupliError("E020", name=container)
    env = dict(resolved.apps[container].vars)
    argv = cmd or ["bash"]
    completed = run_command(argv, cwd=resolved.space_dir, env=env, check=False)
    raise typer.Exit(code=completed.returncode)


@suppress_known_exceptions
def watch_command(
    ctx: typer.Context,
    services: Annotated[
        list[str] | None,
        typer.Argument(
            help="Service names to watch (default: all).",
            autocompletion=complete_service_names,
        ),
    ] = None,
) -> None:
    """Watch source files and react via ``docker compose watch``."""
    _, plan = _build_plan(ctx, services or [])
    invoke(plan, ["watch", *plan.services])


@suppress_known_exceptions
def shortcut_command(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(
            help="Workspace command name. Omit to list available shortcuts.",
            autocompletion=complete_shortcut_names,
        ),
    ] = None,
    extra: Annotated[
        list[str] | None,
        typer.Argument(help="Args for the command (declared args, or appended after it)."),
    ] = None,
) -> None:
    """Run a workspace command from ``commands:`` (omit name to list)."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))

    if name is None:
        _list_shortcuts(resolved)
        return

    shortcut = _lookup_shortcut(resolved, name)
    _, plan = _build_plan(ctx)
    code = _execute_shortcut(plan, name, shortcut, extra or [])
    raise typer.Exit(code=code)


def run_shortcut_resolved(ctx: typer.Context, name: str, values: dict[str, object]) -> None:
    """Run a promoted top-level shortcut with already-parsed argument values.

    Called by the dynamically registered ``cupli <name>`` command, whose typed
    parameters click has already parsed into ``values``.
    """
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    shortcut = resolved.space.commands[name]
    _, plan = _build_plan(ctx)
    run = render_run(shortcut.run, specs_from_models(shortcut.args), values)
    code = _run_across_containers(plan, list(shortcut.container), shortcut.workdir, run, shortcut.execute, None)
    raise typer.Exit(code=code)


def _lookup_shortcut(resolved: ResolvedSpace, name: str) -> CommandShortcut:
    """Return the named shortcut or raise ``E020`` with fuzzy suggestions."""
    if name in resolved.space.commands:
        return resolved.space.commands[name]
    from cupli.utils.fuzzy import suggest

    suggestions = suggest(name, list(resolved.space.commands))
    title = f"unknown workspace command '{name}'"
    if suggestions:
        title += f"; did you mean: {', '.join(suggestions)}"
    raise CupliError("E020", name=title)


def _execute_shortcut(plan: CompiledPlan, name: str, shortcut: CommandShortcut, extra: list[str]) -> int:
    """Render and run a shortcut, returning the aggregate exit code.

    With declared ``args`` the trailing tokens are parsed and substituted into
    ``run``; without them the tokens are appended as positional ``$@`` for
    backward compatibility.
    """
    containers = list(shortcut.container)
    if not shortcut.args:
        return _run_across_containers(plan, containers, shortcut.workdir, shortcut.run, shortcut.execute, extra or None)
    run = _render_with_args(name, shortcut, extra)
    return _run_across_containers(plan, containers, shortcut.workdir, run, shortcut.execute, None)


def _render_with_args(name: str, shortcut: CommandShortcut, extra: list[str]) -> str:
    """Parse ``extra`` against declared args and render the ``run`` line."""
    specs = specs_from_models(shortcut.args)
    try:
        values = parse_extra(specs, extra)
    except click.UsageError as exc:
        raise CupliError("E020", name=f"command '{name}': {exc.format_message()}") from exc
    return render_run(shortcut.run, specs, values)


# --- multi-container execution ---------------------------------------------


def _run_across_containers(
    plan: CompiledPlan,
    containers: list[str],
    workdir: str | None,
    run: str,
    mode: ExecuteMode,
    passthrough: list[str] | None,
) -> int:
    """Run ``run`` across every container per the execution ``mode``."""
    if mode is ExecuteMode.PARALLEL:
        return _run_parallel(plan, containers, workdir, run, passthrough)
    return _run_sequential(plan, containers, workdir, run, mode, passthrough)


def _run_sequential(
    plan: CompiledPlan,
    containers: list[str],
    workdir: str | None,
    run: str,
    mode: ExecuteMode,
    passthrough: list[str] | None,
) -> int:
    """Run containers one by one; fail-fast for SEQUENTIAL, run-all for CONTINUE."""
    aggregate = 0
    for container in containers:
        completed = invoke(plan, _build_exec_args(container, workdir, run, passthrough), check=False)
        if completed.returncode == 0:
            continue
        if mode is ExecuteMode.SEQUENTIAL:
            return completed.returncode
        aggregate = aggregate or completed.returncode
    return aggregate


def _run_parallel(
    plan: CompiledPlan,
    containers: list[str],
    workdir: str | None,
    run: str,
    passthrough: list[str] | None,
) -> int:
    """Run every container concurrently, capturing output to avoid interleaving."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[str, CompletedProcess[str]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(containers))) as pool:
        futures = {pool.submit(_invoke_capture, plan, c, workdir, run, passthrough): c for c in containers}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return _report_parallel(containers, results)


def _invoke_capture(
    plan: CompiledPlan,
    container: str,
    workdir: str | None,
    run: str,
    passthrough: list[str] | None,
) -> CompletedProcess[str]:
    """Run one container's command with output captured (no streaming)."""
    return invoke(plan, _build_exec_args(container, workdir, run, passthrough), stream=False, check=False)


def _report_parallel(containers: list[str], results: dict[str, CompletedProcess[str]]) -> int:
    """Print each container's captured output under a header; aggregate exit code."""
    from cupli.utils.console import console

    aggregate = 0
    for container in containers:
        completed = results[container]
        console.rule(f"{container} (exit {completed.returncode})")
        _echo_capture(completed)
        aggregate = aggregate or completed.returncode
    return aggregate


def _echo_capture(completed: CompletedProcess[str]) -> None:
    """Write a captured process's stdout/stderr verbatim."""
    if completed.stdout:
        typer.echo(completed.stdout, nl=False)
    if completed.stderr:
        typer.echo(completed.stderr, nl=False)


def _build_exec_args(container: str, workdir: str | None, run: str, passthrough: list[str] | None) -> list[str]:
    """Build the ``docker compose exec`` argv for one container.

    ``run`` is wrapped in ``sh -c`` so operators (``&&``, ``|``, ``$VAR``)
    expand inside the container. When ``passthrough`` is given (no declared
    args), the tokens become positional parameters for the snippet.
    """
    args = ["exec"]
    if workdir:
        args.extend(["--workdir", workdir])
    args.append(container)
    if not passthrough:
        args.extend(["sh", "-c", run])
        return args
    # Auto-append ``"$@"`` only for a single-line snippet; a multi-line script
    # still receives the tokens as positional parameters ($1, $2, …) but is not
    # mangled by appending to its last line.
    script = f'{run} "$@"' if "\n" not in run else run
    args.extend(["sh", "-c", script, "_", *passthrough])
    return args


# --- listing ---------------------------------------------------------------


def _list_shortcuts(resolved: ResolvedSpace) -> None:
    """Print declared ``commands:`` as one rich table per group."""
    from cupli.utils.console import console, info

    commands = resolved.space.commands
    if not commands:
        info("no workspace commands declared; add a `commands:` block to your space yaml.")
        return
    for group_name, names in _group_command_names(commands).items():
        console.print(_shortcut_table(group_name, commands, names))


def _group_command_names(commands: dict[str, CommandShortcut]) -> dict[str, list[str]]:
    """Map each group label to its sorted command names (ungrouped last)."""
    groups: dict[str, list[str]] = {}
    for name in sorted(commands):
        label = commands[name].group or COMMANDS_PANEL_TITLE
        groups.setdefault(label, []).append(name)
    return groups


def _shortcut_table(group_name: str, commands: dict[str, CommandShortcut], names: list[str]):
    """Build a rich table for one group of shortcuts."""
    from rich.table import Table

    table = Table(title=group_name, show_lines=False, expand=False)
    for column, style in (
        ("name", "cyan"),
        ("containers", "white"),
        ("command", "white"),
        ("args", "dim"),
        ("help", "dim"),
    ):
        table.add_column(column, style=style, no_wrap=column in {"name", "containers"})
    for name in names:
        shortcut = commands[name]
        table.add_row(
            name,
            ", ".join(shortcut.container),
            _first_line(shortcut.run),
            _args_summary(shortcut.args),
            shortcut.help or "",
        )
    return table


def _first_line(run: str) -> str:
    """Return the first line of ``run`` with an ellipsis when it spans more."""
    lines = run.splitlines()
    if len(lines) <= 1:
        return run
    return f"{lines[0]} …"


def _args_summary(args: list[CommandArg]) -> str:
    """Render a compact label for declared args (``<req> [opt] --flag``)."""
    return " ".join(_arg_label(arg) for arg in args)


def _arg_label(arg: CommandArg) -> str:
    """Return the compact display label for one declared arg."""
    if arg.is_option:
        return f"--{arg.name}"
    if arg.required:
        return f"<{arg.name}>"
    return f"[{arg.name}]"


@suppress_known_exceptions
def upgrade_config_command(_: typer.Context) -> None:
    """Placeholder for future ``schema_version`` migrations."""
    from cupli.utils.console import success

    success("schema_version 1 is current; no migration needed.")


@suppress_known_exceptions
def env_command(
    ctx: typer.Context,
    container: Annotated[
        str | None,
        typer.Option(
            "--container",
            "-c",
            help="Print this app's resolved scope instead of the space scope.",
            autocompletion=complete_app_names,
        ),
    ] = None,
    export: Annotated[
        bool,
        typer.Option("--export", help="Prefix every line with ``export `` for sh ``eval``."),
    ] = False,
) -> None:
    """Print the env that ``cupli`` injects into ``docker compose``.

    Without ``-c``, prints the space-scope variables plus the ``COMPOSE_*``
    pointers (``COMPOSE_FILE``, ``COMPOSE_PROJECT_NAME``,
    ``COMPOSE_PROJECT_DIRECTORY``, ``COMPOSE_PATH_SEPARATOR``).

    With ``-c <name>``, prints the resolved scope of that app.

    Use ``eval "$(cupli env --export)"`` to import the env into the current
    shell — ``docker compose ...`` will transparently pick up cupli's setup.
    """
    import sys

    from cupli.services.compose_service import build_env, make_plan

    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    compose_env = build_env(make_plan(resolved))

    if container is None:
        scope = {**resolved.space_vars, **compose_env}
    else:
        if container not in resolved.apps:
            raise CupliError("E020", name=container)
        scope = {**resolved.apps[container].vars, **compose_env}

    prefix = "export " if export else ""
    # Bypass rich.console here: this command's output is meant to be machine-
    # parsed (eval, grep). Rich would truncate long ``COMPOSE_FILE`` values.
    for key in sorted(scope):
        sys.stdout.write(f"{prefix}{key}={scope[key]}\n")
    sys.stdout.flush()


completion_app = typer.Typer(
    name="completion",
    help="Install or print cupli's shell-completion script.",
    no_args_is_help=True,
)


def _detect_shell() -> str:
    """Best-effort guess at the current shell name (bash/zsh/fish/pwsh)."""
    import os
    from pathlib import Path

    shell_path = os.environ.get("SHELL", "")
    if not shell_path:
        return "bash"
    name = Path(shell_path).name.lower()
    if name in {"bash", "zsh", "fish"}:
        return name
    if name in {"pwsh", "powershell"}:
        return "pwsh"
    return "bash"


@completion_app.command(name="install")
@suppress_known_exceptions
def completion_install(
    shell: Annotated[
        str | None,
        typer.Option("--shell", help="Shell name. Auto-detected from $SHELL when omitted."),
    ] = None,
) -> None:
    """Install cupli's shell-completion script for the current user."""
    import subprocess

    from cupli.utils.console import info, success

    target = shell or _detect_shell()
    info(f"installing completion for {target} ...")
    result = subprocess.run(
        ["cupli", "--install-completion", target],
        check=False,
    )
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
    success(f"completion installed for {target}; restart your shell to activate.")


@completion_app.command(name="show")
@suppress_known_exceptions
def completion_show(
    shell: Annotated[
        str | None,
        typer.Option("--shell", help="Shell name. Auto-detected from $SHELL when omitted."),
    ] = None,
) -> None:
    """Print the shell-completion script without installing it (eval-friendly)."""
    import subprocess

    target = shell or _detect_shell()
    result = subprocess.run(
        ["cupli", "--show-completion", target],
        check=False,
    )
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


# --- helpers ---------------------------------------------------------------


def _build_plan(ctx: typer.Context, services: list[str] | None = None):
    """Compile a plan for an exec/run/wrap invocation."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    plan = make_plan(resolved, services=services or [])
    return resolved, plan


__all__ = (
    "completion_app",
    "env_command",
    "exec_command",
    "run_cli_command",
    "run_shortcut_resolved",
    "shell_command",
    "shortcut_command",
    "upgrade_config_command",
    "watch_command",
    "wrap_command",
)
