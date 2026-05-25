"""``cupli hooks install`` / ``cupli hooks remove`` and the hidden ``__run-hook__``."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003  --  typer resolves Path annotations at runtime
from typing import Annotated

import typer

from cupli.cli._completion import (
    complete_app_names,
    complete_hook_scope,
    complete_hook_targets,
)
from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.services.hooks_service import (
    install_hooks,
    run_hook,
    uninstall_hooks,
)
from cupli.utils.console import error, info, success
from cupli.utils.exceptions import suppress_known_exceptions

hooks_app = typer.Typer(
    name="hooks",
    help="Install/remove per-target git-hook shims that dispatch into docker.",
    no_args_is_help=True,
)


@suppress_known_exceptions
def set_hooks_command(
    ctx: typer.Context,
    hooks_dir: Annotated[Path, typer.Argument(help="Directory containing pre-commit/, pre-push/, …")],
    scope: Annotated[
        str,
        typer.Option("--scope", help="apps | bases | mounts | all.", autocompletion=complete_hook_scope),
    ] = "all",
    targets: Annotated[
        list[str] | None,
        typer.Option("--target", help="Restrict to these target names.", autocompletion=complete_hook_targets),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite foreign hooks and pre-commit conflicts.")] = False,
) -> None:
    """Install per-target git-hook shims that dispatch into docker containers."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    report = install_hooks(
        resolved,
        hooks_dir.resolve(),
        scope=scope,
        targets_filter=tuple(targets or ()),
        force=force,
    )
    for row in report.installed:
        success(f"installed {row}")
    for row in report.conflicts:
        error(row)
    if report.conflicts:
        raise typer.Exit(code=1)


@suppress_known_exceptions
def unset_hooks_command(
    ctx: typer.Context,
    scope: Annotated[
        str,
        typer.Option("--scope", help="apps | bases | mounts | all.", autocompletion=complete_hook_scope),
    ] = "all",
    targets: Annotated[
        list[str] | None,
        typer.Option("--target", help="Restrict to these target names.", autocompletion=complete_hook_targets),
    ] = None,
) -> None:
    """Remove every shim previously installed by ``cupli set-hooks``."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    report = uninstall_hooks(resolved, scope=scope, targets_filter=tuple(targets or ()))
    for row in report.removed:
        success(f"removed {row}")
    if not report.removed:
        info("no cupli-managed hooks were found.")


@suppress_known_exceptions
def run_hook_internal_command(
    ctx: typer.Context,
    hooks_dir: Annotated[Path, typer.Option("--hooks-dir", help="Absolute hooks dir.")],
    hook: Annotated[str, typer.Option("--hook", help="Git hook name (e.g. pre-commit).")],
    default_container: Annotated[
        str,
        typer.Option(
            "--default-container",
            help="Default container for scripts.",
            autocompletion=complete_app_names,
        ),
    ],
    default_workdir: Annotated[str, typer.Option("--default-workdir", help="Default workdir for scripts.")] = "",
    extra: Annotated[list[str] | None, typer.Argument(help="Extra args forwarded to each script.")] = None,
) -> None:
    """Invoked by generated shims. Iterate scripts and dispatch each.

    This command is not meant for human use; the shim invokes it.
    """
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    code = run_hook(
        resolved,
        hooks_dir=hooks_dir.resolve(),
        hook=hook,
        default_container=default_container,
        default_workdir=default_workdir,
        extra_args=extra or [],
    )
    if code != 0:
        raise typer.Exit(code=code)


hooks_app.command(name="install", help="Install per-target git-hook shims that dispatch into docker.")(
    set_hooks_command,
)
hooks_app.command(name="remove", help="Remove cupli-managed hook shims.")(
    unset_hooks_command,
)


__all__ = (
    "hooks_app",
    "run_hook_internal_command",
    "set_hooks_command",
    "unset_hooks_command",
)
