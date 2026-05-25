"""``cupli dashboard`` — minimal live status of workspace services.

A small Rich ``Live`` display that polls ``docker compose ps`` on a 2-second
cadence and re-renders the table. Press Ctrl-C to exit.

Designed as a low-overhead first step toward the v2-plan §0 idea of a
Textual TUI; if/when we adopt Textual, this command rebinds to the new app.
"""

from __future__ import annotations

import subprocess
import time
from typing import Annotated

import typer
from rich.live import Live
from rich.table import Table

from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.services.compose_service import build_argv, make_plan
from cupli.utils.console import console
from cupli.utils.exceptions import suppress_known_exceptions


@suppress_known_exceptions
def dashboard_command(
    ctx: typer.Context,
    interval: Annotated[float, typer.Option("--interval", "-i", help="Polling interval in seconds.")] = 2.0,
) -> None:
    """Live status table of workspace services (Ctrl-C to exit)."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    plan = make_plan(resolved)
    argv = build_argv(plan, ["ps", "--format", "json", "-a"])

    with Live(_blank_table(), console=console, refresh_per_second=4, transient=False) as live:
        try:
            while True:
                live.update(_render_table(argv))
                time.sleep(max(0.5, interval))
        except KeyboardInterrupt:
            pass


def _render_table(argv: list[str]) -> Table:
    """Run ``docker compose ps --format json`` and render the output as a table."""
    rows = _read_rows(argv)
    table = Table(title="Cupli dashboard (Ctrl-C to exit)", show_lines=False)
    table.add_column("service", style="cyan", no_wrap=True)
    table.add_column("state", style="white")
    table.add_column("image", style="white")
    table.add_column("ports", style="white")
    if not rows:
        table.add_row("(no services)", "—", "—", "—")
        return table
    for row in rows:
        state = row.get("State", "?")
        styled_state = f"[green]{state}[/green]" if state == "running" else f"[yellow]{state}[/yellow]"
        table.add_row(
            row.get("Service", row.get("Name", "?")),
            styled_state,
            row.get("Image", "?"),
            row.get("Publishers") and str(row["Publishers"]) or "—",
        )
    return table


def _blank_table() -> Table:
    """Initial table shown before the first poll completes."""
    table = Table(title="Cupli dashboard (warming up)")
    table.add_column("status")
    table.add_row("polling …")
    return table


def _read_rows(argv: list[str]) -> list[dict]:
    """Parse the JSON output of ``docker compose ps --format json``."""
    import json

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    rows: list[dict] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


__all__ = ("dashboard_command",)
