"""Compose lifecycle CLI commands.

Wraps :mod:`cupli.services.compose_service` into the typer commands that
users invoke day-to-day: ``up``, ``stop``, ``restart``, ``down``,
``ps``, ``logs``, ``build``, ``pull``, ``compose``.
"""

from __future__ import annotations

from typing import Annotated

import typer

from cupli.cli._completion import complete_service_names, complete_tag_names
from cupli.cli.workspace import _resolve_space_path, _strict_vars
from cupli.core.loader import load_space
from cupli.domain.enums import DepMode
from cupli.domain.errors import CupliError
from cupli.services.compose_service import invoke, make_plan
from cupli.utils.exceptions import suppress_known_exceptions


def _plan(ctx: typer.Context, services: list[str], tags: list[str], mode: DepMode | None = None):
    """Resolve a :class:`CompiledPlan` for the current invocation."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    return resolved, make_plan(resolved, services=services, tags=tags, mode=mode)


def _parse_mode(raw: str | None) -> DepMode | None:
    """Coerce a CLI ``--mode`` value to a :class:`DepMode`."""
    if raw is None:
        return None
    try:
        return DepMode(raw)
    except ValueError as exc:
        valid = ", ".join(m.value for m in DepMode)
        raise CupliError("E020", name=f"--mode must be one of {valid}, got {raw!r}") from exc


@suppress_known_exceptions
def up_command(
    ctx: typer.Context,
    services: Annotated[
        list[str] | None,
        typer.Argument(help="Service names.", autocompletion=complete_service_names),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Tag filter (repeatable).", autocompletion=complete_tag_names),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option("--mode", help=f"Dep-mode filter: {', '.join(m.value for m in DepMode)}."),
    ] = None,
    detach: Annotated[bool, typer.Option("--detach", "-d", help="Run in detached mode.")] = False,
    build: Annotated[bool, typer.Option("--build", help="Build images before starting.")] = False,
    pull: Annotated[str, typer.Option("--pull", help="Pull policy: missing|always|never.")] = "missing",
) -> None:
    """Bring services up (``docker compose up``)."""
    _, plan = _plan(ctx, services or [], tag or [], _parse_mode(mode))
    args = ["up"]
    if detach:
        args.append("-d")
    if build:
        args.append("--build")
    args.extend(["--pull", pull])
    args.extend(plan.services)
    invoke(plan, args)


@suppress_known_exceptions
def stop_command(
    ctx: typer.Context,
    services: Annotated[
        list[str] | None,
        typer.Argument(help="Service names.", autocompletion=complete_service_names),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Tag filter.", autocompletion=complete_tag_names),
    ] = None,
) -> None:
    """Stop services (containers remain on disk)."""
    _, plan = _plan(ctx, services or [], tag or [])
    invoke(plan, ["stop", *plan.services])


@suppress_known_exceptions
def restart_command(
    ctx: typer.Context,
    services: Annotated[
        list[str] | None,
        typer.Argument(help="Service names.", autocompletion=complete_service_names),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Tag filter.", autocompletion=complete_tag_names),
    ] = None,
    hard: Annotated[bool, typer.Option("--hard", help="Down + up -d (recreate containers).")] = False,
) -> None:
    """Restart services (``--hard`` recreates containers)."""
    _, plan = _plan(ctx, services or [], tag or [])
    if hard:
        invoke(plan, ["down", "--remove-orphans"])
        invoke(plan, ["up", "-d", *plan.services])
        return
    invoke(plan, ["restart", *plan.services])


@suppress_known_exceptions
def down_command(
    ctx: typer.Context,
    volumes: Annotated[bool, typer.Option("--volumes", "-v", help="Also remove volumes.")] = False,
    images: Annotated[bool, typer.Option("--images", help="Also remove built images.")] = False,
) -> None:
    """Tear the workspace down (``docker compose down``)."""
    _, plan = _plan(ctx, [], [])
    args = ["down", "--remove-orphans"]
    if volumes:
        args.append("--volumes")
    if images:
        args.extend(["--rmi", "local"])
    invoke(plan, args)


@suppress_known_exceptions
def ps_command(
    ctx: typer.Context,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Tag filter.", autocompletion=complete_tag_names),
    ] = None,
) -> None:
    """Show running services."""
    _, plan = _plan(ctx, [], tag or [])
    invoke(plan, ["ps", *plan.services])


@suppress_known_exceptions
def logs_command(
    ctx: typer.Context,
    service: Annotated[
        str | None,
        typer.Argument(help="Service name (omit for all).", autocompletion=complete_service_names),
    ] = None,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output.")] = False,
    tail: Annotated[int, typer.Option("--tail", help="Number of trailing lines.")] = 200,
) -> None:
    """Show service logs. Omit the name to stream all services with compose's per-service colours."""
    _, plan = _plan(ctx, [], [])
    args = ["logs", "--tail", str(tail)]
    if follow:
        args.append("-f")
    if service is not None:
        args.append(service)
    invoke(plan, args)


@suppress_known_exceptions
def build_command(
    ctx: typer.Context,
    services: Annotated[
        list[str] | None,
        typer.Argument(help="Service names.", autocompletion=complete_service_names),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Tag filter.", autocompletion=complete_tag_names),
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable build cache.")] = False,
    pull: Annotated[bool, typer.Option("--pull", help="Pull base images first.")] = False,
) -> None:
    """Build service images."""
    _, plan = _plan(ctx, services or [], tag or [])
    args = ["build"]
    if no_cache:
        args.append("--no-cache")
    if pull:
        args.append("--pull")
    args.extend(plan.services)
    invoke(plan, args)


@suppress_known_exceptions
def pull_command(
    ctx: typer.Context,
    services: Annotated[
        list[str] | None,
        typer.Argument(help="Service names.", autocompletion=complete_service_names),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Tag filter.", autocompletion=complete_tag_names),
    ] = None,
) -> None:
    """Pull service images."""
    _, plan = _plan(ctx, services or [], tag or [])
    invoke(plan, ["pull", *plan.services])


@suppress_known_exceptions
def compose_command(
    ctx: typer.Context,
    args: Annotated[list[str] | None, typer.Argument(help="Args forwarded to docker compose.")] = None,
) -> None:
    """Pass-through to ``docker compose`` with cupli's ``-f``/``--env-file`` injected."""
    _, plan = _plan(ctx, [], [])
    invoke(plan, args or [])


@suppress_known_exceptions
def config_command(
    ctx: typer.Context,
) -> None:
    """Print the fully-merged compose configuration."""
    _, plan = _plan(ctx, [], [])
    invoke(plan, ["config"])


__all__ = (
    "build_command",
    "compose_command",
    "config_command",
    "down_command",
    "logs_command",
    "ps_command",
    "pull_command",
    "restart_command",
    "stop_command",
    "up_command",
)
