"""``cupli graph`` / ``cupli stats`` — at-a-glance discovery commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.tree import Tree

from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.services.compose_service import build_env, make_plan
from cupli.utils.console import console
from cupli.utils.exceptions import suppress_known_exceptions
from cupli.utils.subprocess import run_command


@suppress_known_exceptions
def graph_command(ctx: typer.Context) -> None:
    """Print a tree of bases / apps + deps + mounts + exports for the current space."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))

    root = Tree(f"[bold cyan]{resolved.space.name}[/bold cyan] [dim]({resolved.space_dir})[/dim]")
    if resolved.space.bases:
        bases_node = root.add("[bold]bases[/bold]")
        for name in sorted(resolved.space.bases):
            bases_node.add(f"[white]{name}[/white]")
    apps_node = root.add("[bold]apps[/bold]")
    for name in sorted(resolved.space.apps):
        app = resolved.space.apps[name]
        label = f"[white]{name}[/white]"
        if app.tags:
            label += f"  [dim]tags={','.join(app.tags)}[/dim]"
        label += f"  [dim]mode={app.mode.value}[/dim]"
        node = apps_node.add(label)
        if app.bases:
            node.add(f"[dim]bases: {', '.join(app.bases)}[/dim]")
        if app.deps:
            deps_str = ", ".join(f"{dep} [{','.join(m.value for m in spec.modes)}]" for dep, spec in app.deps.items())
            node.add(f"[yellow]deps:[/yellow] {deps_str}")
    if resolved.space.mounts:
        mounts_node = root.add("[bold]mounts[/bold]")
        for name in sorted(resolved.space.mounts):
            mount = resolved.space.mounts[name]
            mounts_node.add(
                f"[white]{name}[/white] -> [green]{', '.join(mount.hosted_in)}[/green]"
                f"  [dim]exec_path={mount.exec_path}[/dim]",
            )
    if resolved.space.exports:
        exports_node = root.add("[bold]exports[/bold]")
        for name in sorted(resolved.space.exports):
            export = resolved.space.exports[name]
            exports_node.add(
                f"[white]{name}[/white] [dim]from[/dim] [green]{export.from_app}[/green]"
                f"  [dim]{export.exec_path} -> {resolved.exports[name].path}"
                f"  ({export.strategy.value})[/dim]",
            )
    if resolved.space.commands:
        cmd_node = root.add("[bold]commands[/bold]")
        for cmd_name in sorted(resolved.space.commands):
            sc = resolved.space.commands[cmd_name]
            cmd_node.add(f"[cyan]{cmd_name}[/cyan]  [dim]in {sc.container}: {sc.run}[/dim]")
    console.print(root)


@suppress_known_exceptions
def stats_command(
    ctx: typer.Context,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Stream stats live.")] = False,
) -> None:
    """Show docker resource usage for workspace services (wrapper over ``docker stats``)."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    plan = make_plan(resolved)
    env = build_env(plan)
    args = ["docker", "stats"]
    if not follow:
        args.append("--no-stream")
    run_command(args, cwd=plan.project_dir, env=env)


__all__ = ("graph_command", "stats_command")
