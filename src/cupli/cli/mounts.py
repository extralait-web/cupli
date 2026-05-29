"""``cupli mounts list / attach / detach`` commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from cupli.cli._completion import complete_mount_names
from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.services.mounts_service import (
    attach as svc_attach,
)
from cupli.services.mounts_service import (
    detach as svc_detach,
)
from cupli.services.mounts_service import (
    list_mounts,
)
from cupli.utils.console import console, success
from cupli.utils.exceptions import suppress_known_exceptions

_BRIDGE_STYLE = {
    "ok": "[green]ok[/green]",
    "broken": "[yellow]broken[/yellow]",
    "conflict": "[red]conflict[/red]",
    "pending": "[cyan]pending[/cyan]",
    "none": "[dim]-[/dim]",
}
"""Rendering for the ``bridge`` column of ``cupli mounts list``."""

mounts_app = typer.Typer(
    name="mounts",
    help="Inspect and toggle library mounts.",
    no_args_is_help=True,
)


@mounts_app.command(name="list")
@suppress_known_exceptions
def mounts_list_command(ctx: typer.Context) -> None:
    """Show every declared mount with its current state."""
    from cupli.services.bridge_service import bridge_info

    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    rows = list_mounts(resolved)
    bridges = bridge_info(resolved)

    table = Table(title="Mounts", show_lines=False, expand=False)
    table.add_column("name", style="cyan", no_wrap=True)
    table.add_column("host path", style="white")
    table.add_column("exec path", style="white")
    table.add_column("hosted_in", style="white")
    table.add_column("mode", style="white")
    table.add_column("active", style="white")
    table.add_column("cloned", style="white")
    table.add_column("bridge", style="white")
    for row in rows:
        status = bridges[row.name].status if row.name in bridges else "none"
        table.add_row(
            row.name,
            str(row.host_path),
            row.exec_path,
            ", ".join(row.hosted_in),
            row.mode,
            "[green]yes[/green]" if row.active else "[yellow]no[/yellow]",
            "[green]yes[/green]" if row.cloned else "[red]no[/red]",
            _BRIDGE_STYLE.get(status, status),
        )
    console.print(table)


@mounts_app.command(name="attach")
@suppress_known_exceptions
def mounts_attach_command(
    ctx: typer.Context,
    name: Annotated[
        str,
        typer.Argument(help="Mount name.", autocompletion=complete_mount_names),
    ],
    restart: Annotated[
        bool, typer.Option("--restart/--no-restart", help="Restart affected services to apply the change.")
    ] = True,
) -> None:
    """Mark a mount as active and (by default) restart the affected services."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    svc_attach(resolved, name)
    success(f"mount {name} attached.")
    if restart:
        _restart_hosting_services(resolved, name)


@mounts_app.command(name="detach")
@suppress_known_exceptions
def mounts_detach_command(
    ctx: typer.Context,
    name: Annotated[
        str,
        typer.Argument(help="Mount name.", autocompletion=complete_mount_names),
    ],
    restart: Annotated[
        bool, typer.Option("--restart/--no-restart", help="Restart affected services to apply the change.")
    ] = True,
) -> None:
    """Mark a mount as inactive and (by default) restart the affected services."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    from cupli.services.bridge_service import unbridge_mounts

    svc_detach(resolved, name)
    if resolved.space.mounts[name].bridge_enabled:
        unbridge_mounts(resolved, [name])
    success(f"mount {name} detached.")
    if restart:
        _restart_hosting_services(resolved, name)


@mounts_app.command(name="bridge")
@suppress_known_exceptions
def mounts_bridge_command(
    ctx: typer.Context,
    names: Annotated[
        list[str] | None,
        typer.Argument(
            help="Mount names (default: all active host_bridge mounts).", autocompletion=complete_mount_names
        ),
    ] = None,
) -> None:
    """Create or repair host_bridge symlinks for active mounts."""
    from cupli.services.bridge_service import bridge_mounts

    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    results = bridge_mounts(resolved, names)
    if not results:
        console.print("[dim]no host_bridge mounts to bridge.[/dim]")
        return
    for res in results:
        console.print(f"{res.name}: {res.status}" + (f" ({res.detail})" if res.detail else ""))
    success("bridges up to date.")


@mounts_app.command(name="unbridge")
@suppress_known_exceptions
def mounts_unbridge_command(
    ctx: typer.Context,
    names: Annotated[
        list[str] | None,
        typer.Argument(help="Mount names (default: all cupli-created bridges).", autocompletion=complete_mount_names),
    ] = None,
) -> None:
    """Remove host_bridge symlinks cupli created."""
    from cupli.services.bridge_service import unbridge_mounts

    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    results = unbridge_mounts(resolved, names)
    for res in results:
        console.print(f"{res.name}: {res.status}" + (f" ({res.detail})" if res.detail else ""))
    success("bridges removed.")


def _restart_hosting_services(resolved, mount_name: str) -> None:
    """Restart every service that hosts ``mount_name`` so the change lands."""
    from cupli.services.compose_service import invoke, make_plan

    hosts = [app for app in resolved.space.mounts[mount_name].hosted_in if app in resolved.space.apps]
    if not hosts:
        return
    plan = make_plan(resolved, services=hosts)
    invoke(plan, ["up", "-d", *plan.services])


__all__ = ("mounts_app",)
