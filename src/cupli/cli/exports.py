"""``cupli exports list / sync / clean`` commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.utils.console import console, success
from cupli.utils.exceptions import suppress_known_exceptions

exports_app = typer.Typer(
    name="exports",
    help="Materialise container-built directories (node_modules, …) onto the host for IDEs.",
    no_args_is_help=True,
)

_STATUS_STYLE = {
    "synced": "[green]synced[/green]",
    "seeded": "[green]seeded[/green]",
    "stale": "[yellow]stale[/yellow]",
    "missing": "[red]missing[/red]",
}
"""Rendering for the ``status`` column of ``cupli exports list``."""


@exports_app.command(name="list")
@suppress_known_exceptions
def exports_list_command(ctx: typer.Context) -> None:
    """Show every declared export with its current state."""
    from cupli.services.exports_service import list_exports

    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    rows = list_exports(resolved)

    table = Table(title="Exports", show_lines=False, expand=False)
    table.add_column("name", style="cyan", no_wrap=True)
    table.add_column("from", style="white")
    table.add_column("exec path", style="white")
    table.add_column("host path", style="white")
    table.add_column("strategy", style="white")
    table.add_column("status", style="white")
    for row in rows:
        table.add_row(
            row.name,
            row.from_app,
            row.exec_path,
            str(row.path),
            row.strategy,
            _STATUS_STYLE.get(row.status, row.status),
        )
    console.print(table)


@exports_app.command(name="sync")
@suppress_known_exceptions
def exports_sync_command(
    ctx: typer.Context,
    names: Annotated[
        list[str] | None,
        typer.Argument(help="Export names (default: all)."),
    ] = None,
) -> None:
    """Materialise / refresh exports onto the host."""
    from cupli.services.exports_service import sync_exports

    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    rows = sync_exports(resolved, names)
    for row in rows:
        console.print(f"{row.name}: {row.status} → {row.path}")
    success("exports synced.")


@exports_app.command(name="clean")
@suppress_known_exceptions
def exports_clean_command(
    ctx: typer.Context,
    names: Annotated[
        list[str] | None,
        typer.Argument(help="Export names (default: all)."),
    ] = None,
) -> None:
    """Remove host copies (``sync`` strategy); ``bind-seeded`` data is kept."""
    from cupli.services.exports_service import clean_exports

    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    rows = clean_exports(resolved, names)
    for row in rows:
        console.print(f"{row.name}: {row.status}")
    success("exports cleaned.")


__all__ = ("exports_app",)
