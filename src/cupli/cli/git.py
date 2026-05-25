"""``cupli git`` — multi-repo git operations.

Subapp grouping ``status`` / ``pull`` / ``fetch`` / ``checkout`` so a day's
work across N repos is one command instead of a shell loop.

Every command accepts an optional positional ``<names>...`` selector to
restrict the operation to a subset of components — empty means "every
cloned repo".
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from cupli.cli._completion import complete_branch_map, complete_hook_targets
from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.domain.errors import CupliError
from cupli.services import git_service
from cupli.utils.console import console
from cupli.utils.exceptions import suppress_known_exceptions

git_app = typer.Typer(
    name="git",
    help="Multi-repo git operations across every cloned component.",
    no_args_is_help=True,
)


_STATE_STYLE: dict[str, str] = {
    "clean": "green",
    "dirty": "yellow",
    "drifted": "yellow",
    "up-to-date": "green",
    "pulled": "cyan",
    "fetched": "cyan",
    "checked-out": "cyan",
    "error": "red",
}


def _render_rows(title: str, rows: list[git_service.GitRow]) -> None:
    """Render a list of :class:`GitRow` as a rich table."""
    table = Table(title=title, show_lines=False, expand=False)
    table.add_column("name", style="cyan", no_wrap=True)
    table.add_column("kind", style="dim", no_wrap=True)
    table.add_column("branch", style="white", no_wrap=True)
    table.add_column("state", no_wrap=True)
    table.add_column("detail", style="white")
    for row in rows:
        style = _STATE_STYLE.get(row.state, "white")
        table.add_row(row.name, row.kind, row.branch, f"[{style}]{row.state}[/{style}]", row.detail)
    console.print(table)


def _has_errors(rows: list[git_service.GitRow]) -> bool:
    return any(row.state == "error" for row in rows)


def _parse_map(items: list[str] | None) -> dict[str, str]:
    """Parse ``--map name=branch`` repeats into a ``{name: branch}`` dict.

    Raises:
        CupliError: ``E020`` when an item does not contain ``=`` or has an
            empty name/branch.
    """
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise CupliError("E020", name=f"--map expects name=branch, got {item!r}")
        name, _, branch = item.partition("=")
        if not name or not branch:
            raise CupliError("E020", name=f"--map name and branch must be non-empty, got {item!r}")
        out[name] = branch
    return out


_TARGETS_OPT = typer.Argument(
    help="Component names to restrict the operation to (default: every cloned repo).",
    autocompletion=complete_hook_targets,
)


@git_app.command(name="status")
@suppress_known_exceptions
def status_command(
    ctx: typer.Context,
    targets: Annotated[list[str] | None, _TARGETS_OPT] = None,
    workers: Annotated[int, typer.Option("--workers", "-j", help="Max parallel git invocations.")] = 4,
) -> None:
    """Print a per-repo status table (branch, clean/dirty/drifted, ahead/behind)."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    rows = git_service.status(resolved, selectors=targets, workers=workers)
    _render_rows("Git status", rows)


@git_app.command(name="pull")
@suppress_known_exceptions
def pull_command(
    ctx: typer.Context,
    targets: Annotated[list[str] | None, _TARGETS_OPT] = None,
    rebase: Annotated[bool, typer.Option("--rebase", help="Use --rebase instead of --ff-only.")] = False,
    workers: Annotated[int, typer.Option("--workers", "-j", help="Max parallel git invocations.")] = 4,
) -> None:
    """Run ``git pull --ff-only`` (or ``--rebase``) in every selected repo, in parallel."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    rows = git_service.pull(resolved, selectors=targets, rebase=rebase, workers=workers)
    _render_rows("Git pull", rows)
    if _has_errors(rows):
        raise typer.Exit(code=1)


@git_app.command(name="fetch")
@suppress_known_exceptions
def fetch_command(
    ctx: typer.Context,
    targets: Annotated[list[str] | None, _TARGETS_OPT] = None,
    workers: Annotated[int, typer.Option("--workers", "-j", help="Max parallel git invocations.")] = 4,
) -> None:
    """Run ``git fetch --prune`` in every selected repo, in parallel."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    rows = git_service.fetch(resolved, selectors=targets, workers=workers)
    _render_rows("Git fetch", rows)
    if _has_errors(rows):
        raise typer.Exit(code=1)


@git_app.command(name="checkout")
@suppress_known_exceptions
def checkout_command(
    ctx: typer.Context,
    branch: Annotated[
        str | None,
        typer.Argument(
            help="Default branch applied to every selected repo (omit when every repo is covered by --map).",
        ),
    ] = None,
    targets: Annotated[
        list[str] | None,
        typer.Option(
            "--target",
            "-t",
            help="Component name to include (repeatable; default: every cloned repo).",
            autocompletion=complete_hook_targets,
        ),
    ] = None,
    branch_map: Annotated[
        list[str] | None,
        typer.Option(
            "--map",
            "-m",
            help="Per-repo override as `name=branch` (repeatable; wins over the default branch).",
            autocompletion=complete_branch_map,
        ),
    ] = None,
    workers: Annotated[int, typer.Option("--workers", "-j", help="Max parallel git invocations.")] = 4,
) -> None:
    """Switch repos to a branch.

    Examples::

        cupli git checkout main                          # every repo
        cupli git checkout main -t shop-api -t shop-web  # only these two
        cupli git checkout -m shop-api=feature/x -m shop-web=main
        cupli git checkout main -m shop-api=feature/x    # everyone on main except shop-api
    """
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    overrides = _parse_map(branch_map)
    rows = git_service.checkout(
        resolved,
        branch,
        selectors=targets,
        overrides=overrides,
        workers=workers,
    )
    title = f"Git checkout {branch}" if branch else "Git checkout (mapped)"
    _render_rows(title, rows)
    if _has_errors(rows):
        raise typer.Exit(code=1)


__all__ = ("git_app",)
