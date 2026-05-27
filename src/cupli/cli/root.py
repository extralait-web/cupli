"""Cupli root typer application.

Global flags, banner, and the discoverability commands (``--version``,
``--list``, ``explain``). Subcommands for workspace/lifecycle/exec/hooks/
mounts/diagnostics are registered in later milestones.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from types import ModuleType

    from cupli.core.cache import CachedCommandRow

from cupli.cli._completion import complete_error_codes
from cupli.cli.container import Container
from cupli.cli.workspace import ide_app, init_command, space_app, workspace_app
from cupli.domain.consts import (
    PANEL_DISCOVERY,
    PANEL_EXEC,
    PANEL_INTEGRATIONS,
    PANEL_LIFECYCLE,
    PANEL_WORKSPACE,
)
from cupli.domain.enums import LogLevel
from cupli.domain.errors import all_codes, error_spec, explain
from cupli.utils.console import configure_logging, console, install_excepthook
from cupli.utils.exceptions import suppress_known_exceptions
from cupli.version import version_info

app = typer.Typer(
    name="cupli",
    help="Cupli — orchestrator for multi-repository docker-compose workspaces.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=True,
)


def _complete_space_names_root(incomplete: str) -> list[str]:
    """Shell-completion for the global ``-s/--space`` option."""
    from cupli.core import registry as _registry
    from cupli.domain.errors import CupliError as _CupliError

    try:
        known = _registry.list_known_spaces()
    except _CupliError:
        return []
    return [name for name in sorted(known) if name.startswith(incomplete)]


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    space_name: Annotated[
        str | None,
        typer.Option(
            "--space",
            "-s",
            help="Name of a registered space.",
            autocompletion=_complete_space_names_root,
        ),
    ] = None,
    space_file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Path to a space.cupli.yaml file."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output (DEBUG level)."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress everything except errors."),
    ] = False,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable colour and styling."),
    ] = False,
    strict_vars: Annotated[
        bool,
        typer.Option("--strict-vars", help="Raise on unknown ${VAR} references."),
    ] = False,
    allow_shadow: Annotated[
        bool,
        typer.Option("--allow-shadow", help="Allow user vars to override reserved auto-vars."),
    ] = False,
    time_profile: Annotated[
        bool,
        typer.Option("--time", help="Print phased timings to stderr."),
    ] = False,
    show_version: Annotated[
        bool,
        typer.Option("--version", help="Show full cupli version info (interpreter, platform, …)."),
    ] = False,
    short_version: Annotated[
        bool,
        typer.Option("-V", help="Print only `cupli <version>` and exit (script-friendly)."),
    ] = False,
    list_commands: Annotated[
        bool,
        typer.Option("--list", help="Print every command grouped by area."),
    ] = False,
) -> None:
    """Root command callback wiring global flags into the container."""
    if short_version:
        from cupli.version import VERSION

        console.print(f"cupli {VERSION}")
        raise typer.Exit
    if show_version:
        console.print(version_info())
        raise typer.Exit
    if list_commands:
        _list_commands()
        raise typer.Exit

    level = _resolve_log_level(verbose=verbose, quiet=quiet)
    configure_logging(level, no_color=no_color)
    install_excepthook(debug_mode=verbose)
    ctx.obj = Container(runtime=None)
    # Per-command setup builds a RuntimeContext once a space is loaded.
    ctx.meta["space_name"] = space_name
    ctx.meta["space_file"] = space_file
    ctx.meta["log_level"] = level
    ctx.meta["no_color"] = no_color
    ctx.meta["strict_vars"] = strict_vars
    ctx.meta["allow_shadow"] = allow_shadow
    ctx.meta["time_profile"] = time_profile


@app.command(name="version")
@suppress_known_exceptions
def version_command() -> None:
    """Print cupli version information."""
    console.print(version_info())


@app.command(name="explain")
@suppress_known_exceptions
def explain_command(
    code: Annotated[
        str | None,
        typer.Argument(help="Error code such as E001.", autocompletion=complete_error_codes),
    ] = None,
    list_all: Annotated[
        bool,
        typer.Option("--list", help="List every known error code."),
    ] = False,
) -> None:
    """Explain a cupli error code or list all known codes."""
    if list_all or code is None:
        _print_all_codes()
        return
    console.print(explain(code))


# --- helpers ---------------------------------------------------------------


def _resolve_log_level(*, verbose: bool, quiet: bool) -> LogLevel:
    """Translate verbose/quiet flags into a :class:`LogLevel`."""
    if quiet:
        return LogLevel.ERROR
    if verbose:
        return LogLevel.DEBUG
    return LogLevel.INFO


def _list_commands() -> None:
    """Render the registered commands as a rich table."""
    import click
    from rich.table import Table

    table = Table(title="Cupli commands", show_lines=False, expand=False)
    table.add_column("command", style="cyan", no_wrap=True)
    table.add_column("description", style="white")

    click_command = typer.main.get_command(app)
    if not isinstance(click_command, click.Group):
        return
    for name in sorted(click_command.commands):
        sub = click_command.commands[name]
        if getattr(sub, "hidden", False):
            continue
        table.add_row(name, sub.help or "")
    console.print(table)


def _print_all_codes() -> None:
    """Print every known error code on its own line."""
    for code in all_codes():
        spec = error_spec(code)
        console.print(f"[blue bold]{code}[/blue bold]  {spec['title']}")


app.add_typer(workspace_app, name="workspace", rich_help_panel=PANEL_WORKSPACE)
app.add_typer(space_app, name="space", rich_help_panel=PANEL_WORKSPACE)
app.add_typer(ide_app, name="ide", rich_help_panel=PANEL_INTEGRATIONS)
app.command(name="init", help="Scaffold a new cupli space.", rich_help_panel=PANEL_WORKSPACE)(
    init_command,
)


def _register_lifecycle() -> None:
    """Wire lifecycle commands; in a function to keep root imports light."""
    from cupli.cli import lifecycle

    app.command(name="up", help="Bring services up (docker compose up).", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.up_command,
    )
    app.command(name="down", help="Tear services down (docker compose down).", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.down_command,
    )
    app.command(name="stop", help="Stop running services.", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.stop_command,
    )
    app.command(name="restart", help="Restart services (--hard recreates).", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.restart_command,
    )
    app.command(name="ps", help="Show running services.", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.ps_command,
    )
    app.command(name="logs", help="Stream service logs (no service = all).", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.logs_command,
    )
    app.command(name="build", help="Build service images.", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.build_command,
    )
    app.command(name="pull", help="Pull service images.", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.pull_command,
    )
    app.command(name="compose", help="Pass-through to docker compose.", rich_help_panel=PANEL_LIFECYCLE)(
        lifecycle.compose_command,
    )
    app.command(name="config", help="Print the merged compose configuration.", rich_help_panel=PANEL_DISCOVERY)(
        lifecycle.config_command,
    )


def _register_exec() -> None:
    """Wire exec / run / shell / with / watch / shortcut / upgrade-config / completion."""
    from cupli.cli import exec as exec_mod

    app.command(name="exec", help="Run a command inside a running container.", rich_help_panel=PANEL_EXEC)(
        exec_mod.exec_command,
    )
    app.command(name="run", help="Start a one-shot container and run a command.", rich_help_panel=PANEL_EXEC)(
        exec_mod.run_cli_command,
    )
    app.command(name="shell", help="Open an interactive shell inside a container.", rich_help_panel=PANEL_EXEC)(
        exec_mod.shell_command,
    )
    app.command(name="with", help="Run a host command with a service's env exported.", rich_help_panel=PANEL_EXEC)(
        exec_mod.wrap_command,
    )
    app.command(name="watch", help="docker compose watch — react to source changes.", rich_help_panel=PANEL_LIFECYCLE)(
        exec_mod.watch_command,
    )
    app.command(
        name="sc",
        help="Run a workspace command from `commands:` (no name = list).",
        rich_help_panel=PANEL_EXEC,
        # Let declared-arg flags (e.g. `cupli sc migrate --fake`) reach the
        # command's own parser instead of being rejected by `sc`.
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    )(
        exec_mod.shortcut_command,
    )
    app.command(
        name="upgrade-config",
        help="Migrate space.cupli.yaml to the current schema.",
        rich_help_panel=PANEL_INTEGRATIONS,
    )(
        exec_mod.upgrade_config_command,
    )
    # Completion: install / show subapp (used to be a top-level hint command).
    app.add_typer(exec_mod.completion_app, name="completion", rich_help_panel=PANEL_INTEGRATIONS)
    app.command(name="env", help="Print COMPOSE_* + workspace env cupli injects.", rich_help_panel=PANEL_DISCOVERY)(
        exec_mod.env_command,
    )


def _register_mounts() -> None:
    """Wire the ``mounts`` subapp."""
    from cupli.cli.mounts import mounts_app

    app.add_typer(mounts_app, name="mounts", rich_help_panel=PANEL_INTEGRATIONS)


def _register_hooks() -> None:
    """Wire the ``hooks`` subapp + the hidden ``__run-hook__`` runner."""
    from cupli.cli import hooks

    app.add_typer(hooks.hooks_app, name="hooks", rich_help_panel=PANEL_INTEGRATIONS)
    app.command(name="__run-hook__", hidden=True)(hooks.run_hook_internal_command)


def _register_git() -> None:
    """Wire the ``git`` subapp."""
    from cupli.cli.git import git_app

    app.add_typer(git_app, name="git", rich_help_panel=PANEL_INTEGRATIONS)


def _register_diagnostics() -> None:
    """Wire ``graph`` and ``stats``."""
    from cupli.cli.diagnostics import graph_command, stats_command

    app.command(name="graph", help="Print a tree of bases/apps/mounts/deps.", rich_help_panel=PANEL_DISCOVERY)(
        graph_command,
    )
    app.command(name="stats", help="docker stats wrapper scoped to the workspace.", rich_help_panel=PANEL_DISCOVERY)(
        stats_command,
    )


def _register_dashboard() -> None:
    """Wire the live ``dashboard`` command."""
    from cupli.cli.dashboard import dashboard_command

    app.command(name="dashboard", help="Live status table of workspace services.", rich_help_panel=PANEL_DISCOVERY)(
        dashboard_command,
    )


_register_lifecycle()
_register_exec()
_register_mounts()
_register_hooks()
_register_git()
_register_diagnostics()
_register_dashboard()


def _register_top_level_shortcuts() -> None:
    """Promote workspace ``commands:`` entries with ``top_level: true`` to verbs.

    Source of truth is the per-space cache written by
    :func:`cupli.core.loader.load_space`; that means the first run of any
    cupli command warms the cache, and the next invocation sees the shortcuts
    at top level. Commands without ``top_level: true`` stay reachable only
    via ``cupli sc <name>``.

    Collisions with builtin command names are silently skipped — a workspace
    can never override ``up`` or ``down``.
    """
    from cupli.cli import exec as exec_mod
    from cupli.core import cache, registry
    from cupli.domain.consts import COMMANDS_PANEL_TITLE

    try:
        detected = registry.detect_current_space(Path.cwd())
    except Exception:
        return
    cached = cache.read_commands(detected.path)
    if cached is None or not cached.commands:
        return

    import click

    click_command = typer.main.get_command(app)
    builtin_names: set[str] = set()
    if isinstance(click_command, click.Group):
        builtin_names = set(click_command.commands)

    for shortcut_name, spec in cached.commands.items():
        if not spec.get("top_level"):
            continue
        if shortcut_name in builtin_names:
            continue
        # A malformed or stale cache row must never break `cupli` at import:
        # skip a shortcut that cannot be wired rather than raising.
        try:
            _wire_top_level_shortcut(exec_mod, shortcut_name, spec, COMMANDS_PANEL_TITLE)
        except (ValueError, KeyError, TypeError):
            continue


def _wire_top_level_shortcut(
    exec_mod: ModuleType,
    shortcut_name: str,
    spec: CachedCommandRow,
    default_panel: str,
) -> None:
    """Wire one ``commands.<name>`` entry as a top-level typer command.

    A command with declared ``args`` is registered with a synthetic typed
    signature so its arguments/options appear in ``cupli <name> --help``;
    otherwise it keeps the simple pass-through form. The ``group`` label (when
    set) becomes the help panel.
    """
    panel = spec.get("group") or default_panel
    help_text = spec.get("help") or _default_shortcut_help(spec)
    arg_rows = spec.get("args") or []
    if arg_rows:
        _wire_typed_shortcut(exec_mod, shortcut_name, arg_rows, help_text, panel)
        return
    _wire_plain_shortcut(exec_mod, shortcut_name, help_text, panel)


def _default_shortcut_help(spec: CachedCommandRow) -> str:
    """Build the fallback help string from a cached command spec."""
    containers = ", ".join(spec.get("container") or []) or "?"
    return f"In {containers}: {spec.get('run') or ''}"


def _shortcut_func_name(shortcut_name: str) -> str:
    """Return a valid Python identifier for a shortcut runner function."""
    return f"shortcut_{shortcut_name.replace('-', '_').replace('.', '_')}"


def _wire_plain_shortcut(exec_mod: ModuleType, shortcut_name: str, help_text: str, panel: str) -> None:
    """Register a no-args shortcut: extra tokens pass through to the command."""

    @suppress_known_exceptions
    def _runner(
        ctx: typer.Context,
        extra: Annotated[
            list[str] | None,
            typer.Argument(help="Extra args appended after the declared command."),
        ] = None,
    ) -> None:
        exec_mod.shortcut_command(ctx, name=shortcut_name, extra=extra)

    _runner.__name__ = _shortcut_func_name(shortcut_name)
    _runner.__doc__ = help_text
    app.command(name=shortcut_name, help=help_text, rich_help_panel=panel)(_runner)


def _wire_typed_shortcut(
    exec_mod: ModuleType,
    shortcut_name: str,
    arg_rows: list[dict[str, Any]],
    help_text: str,
    panel: str,
) -> None:
    """Register a shortcut with declared args as a typed top-level command."""
    from cupli.cli._shortcuts import build_signature, specs_from_cache

    signature, annotations = build_signature(specs_from_cache(arg_rows))

    def _runner(ctx: typer.Context, **values: object) -> None:
        exec_mod.run_shortcut_resolved(ctx, shortcut_name, values)

    runner = suppress_known_exceptions(_runner)
    runner.__signature__ = signature  # type: ignore[attr-defined]
    runner.__annotations__ = annotations
    runner.__name__ = _shortcut_func_name(shortcut_name)
    runner.__doc__ = help_text
    app.command(name=shortcut_name, help=help_text, rich_help_panel=panel)(runner)


_register_top_level_shortcuts()


__all__ = ("app",)
