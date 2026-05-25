"""``exec`` / ``run`` / ``shell`` / ``wrap`` commands.

``exec`` and ``run`` are thin proxies over ``docker compose exec`` and
``docker compose run --rm`` respectively. ``shell`` is a convenience
wrapper around ``exec`` that picks ``/bin/bash`` (or another shell via
``--shell``). ``wrap`` runs a command on the HOST while exporting the
container's resolved environment — useful for scripts that need the
service's env vars but cannot run inside docker.
"""

from __future__ import annotations

from typing import Annotated

import typer

from cupli.cli._completion import (
    complete_app_names,
    complete_service_names,
    complete_shortcut_names,
)
from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.domain.errors import CupliError
from cupli.services.compose_service import invoke, make_plan
from cupli.utils.exceptions import suppress_known_exceptions
from cupli.utils.subprocess import run_command


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
        typer.Argument(help="Extra args appended after the declared command."),
    ] = None,
) -> None:
    """Run a workspace command from ``commands:`` (omit name to list)."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))

    if name is None:
        _list_shortcuts(resolved)
        return

    if name not in resolved.space.commands:
        from cupli.utils.fuzzy import suggest

        suggestions = suggest(name, list(resolved.space.commands))
        title = f"unknown workspace command '{name}'"
        if suggestions:
            title += f"; did you mean: {', '.join(suggestions)}"
        raise CupliError("E020", name=title)
    shortcut = resolved.space.commands[name]
    _, plan = _build_plan(ctx)
    args = ["exec"]
    if shortcut.workdir:
        args.extend(["--workdir", shortcut.workdir])
    args.append(shortcut.container)
    # ``run`` is a shell command line — wrap in ``sh -c`` so operators like
    # ``&&``, ``|``, redirects and ``$VAR`` expand inside the container. Extra
    # args become positional parameters for the shell snippet.
    if extra:
        args.extend(["sh", "-c", f'{shortcut.run} "$@"', "_", *extra])
    else:
        args.extend(["sh", "-c", shortcut.run])
    invoke(plan, args)


def _list_shortcuts(resolved) -> None:
    """Print declared ``commands:`` as a rich table."""
    from rich.table import Table

    from cupli.utils.console import console, info

    if not resolved.space.commands:
        info("no workspace commands declared; add a `commands:` block to your space yaml.")
        return
    table = Table(title="Workspace commands", show_lines=False, expand=False)
    table.add_column("name", style="cyan", no_wrap=True)
    table.add_column("container", style="white", no_wrap=True)
    table.add_column("command", style="white")
    table.add_column("help", style="dim")
    for shortcut_name in sorted(resolved.space.commands):
        shortcut = resolved.space.commands[shortcut_name]
        table.add_row(shortcut_name, shortcut.container, shortcut.run, shortcut.help or "")
    console.print(table)


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
    "shell_command",
    "shortcut_command",
    "upgrade_config_command",
    "watch_command",
    "wrap_command",
)
