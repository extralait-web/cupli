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
from cupli.services.compose_service import invoke, make_plan, target_services
from cupli.utils.exceptions import suppress_known_exceptions


def _plan(ctx: typer.Context, services: list[str], tags: list[str], mode: DepMode | None = None):
    """Resolve a :class:`CompiledPlan` for the current invocation."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    return resolved, make_plan(resolved, services=services, tags=tags, mode=mode)


def _compose_passthrough(ctx: typer.Context, services: list[str] | None) -> tuple[list[str], list[str]]:
    """Split forwarded docker-compose flags from real service names.

    With ``ignore_unknown_options`` set on the command, unrecognised tokens land
    either in the ``services`` positional or in ``ctx.args`` depending on their
    position. Both are combined and partitioned by a leading dash: ``-`` / ``--``
    tokens are forwarded to docker compose verbatim, the rest are service names.
    Value-taking flags should use the ``--opt=value`` form so the value is not
    mistaken for a service name.
    """
    tokens = [*(services or []), *ctx.args]
    flags = [token for token in tokens if token.startswith("-")]
    names = [token for token in tokens if not token.startswith("-")]
    return flags, names


def _verb_services(resolved, plan, names: list[str]) -> list[str]:
    """Pick the compose services a per-service verb should act on.

    ``cupli up`` wants the closure-expanded plan (deps must be started first),
    so ``up`` calls ``plan.services`` directly. Per-service verbs (``restart``,
    ``stop``, ``down``, ``ps``, ``build``, ``pull``) should act exactly on what
    the user named; closure-expansion would silently pull in transitive deps
    and surprise the user — ``cupli restart api`` would also restart every
    database the app depends on.

    With explicit ``names``, resolve them via :func:`target_services` (app
    names expand to all their managed compose services, but deps stay
    untouched). With no names, fall back to ``plan.services`` so workspace-
    wide (``cupli restart``) and tag-filtered (``cupli restart --tag api``)
    forms still work.
    """
    if names:
        return list(target_services(resolved, names))
    return list(plan.services)


def _host_pre_up(resolved, plan) -> None:
    """Seed bind-seeded exports before ``up`` (no-op without exports)."""
    from cupli.services.host_sync import pre_up

    pre_up(resolved, plan)


def _host_post(resolved, plan, event: str, service_names: list[str]) -> None:
    """Refresh exports/bridges after a lifecycle op (no-op when not applicable)."""
    from cupli.services.host_sync import post_event

    post_event(resolved, plan, event, service_names)


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
    """Bring services up (``docker compose up``). Unknown flags pass through."""
    flags, names = _compose_passthrough(ctx, services)
    resolved, plan = _plan(ctx, names, tag or [], _parse_mode(mode))
    _host_pre_up(resolved, plan)
    args = ["up"]
    if detach:
        args.append("-d")
    if build:
        args.append("--build")
    args.extend(["--pull", pull])
    args.extend(flags)
    args.extend(plan.services)
    invoke(plan, args)
    _host_post(resolved, plan, "up", list(plan.services))


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
    """Stop services (containers remain on disk).

    Named services stop only the named containers — dependencies stay up.
    Omit arguments to stop the whole workspace.
    """
    flags, names = _compose_passthrough(ctx, services)
    resolved, plan = _plan(ctx, names, tag or [])
    invoke(plan, ["stop", *flags, *_verb_services(resolved, plan, names)])


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
    """Restart services (``--hard`` recreates containers).

    Named services restart only those containers — dependencies stay up.
    ``--hard`` keeps the closure-expanded ``up`` so any deps that happen to be
    down come back; it tears the named services down and brings them up again.
    """
    flags, names = _compose_passthrough(ctx, services)
    resolved, plan = _plan(ctx, names, tag or [])
    targets = _verb_services(resolved, plan, names)
    if hard:
        invoke(plan, ["down", "--remove-orphans", *targets])
        _host_pre_up(resolved, plan)
        invoke(plan, ["up", "-d", *flags, *plan.services])
        _host_post(resolved, plan, "restart", targets)
        return
    invoke(plan, ["restart", *flags, *targets])
    _host_post(resolved, plan, "restart", targets)


@suppress_known_exceptions
def down_command(
    ctx: typer.Context,
    services: Annotated[
        list[str] | None,
        typer.Argument(help="Service names to take down. Omit to tear the whole workspace down."),
    ] = None,
    volumes: Annotated[bool, typer.Option("--volumes", "-v", help="Also remove volumes.")] = False,
    images: Annotated[bool, typer.Option("--images", help="Also remove built images.")] = False,
) -> None:
    """Tear services down (``docker compose down``).

    Without ``services`` arguments the whole workspace goes down. With service
    names, only those containers are stopped and removed (``docker compose
    down`` supports per-service arguments in compose v2). Unknown flags pass
    through to docker compose.
    """
    flags, names = _compose_passthrough(ctx, services)
    args = ["down", "--remove-orphans"]
    if volumes:
        args.append("--volumes")
    if images:
        args.extend(["--rmi", "local"])
    args.extend(flags)
    if names:
        # Named services → only those containers go down; deps stay up.
        resolved, plan = _plan(ctx, names, [])
        args.extend(_verb_services(resolved, plan, names))
    else:
        # No services → workspace-level down (default).
        _, plan = _plan(ctx, [], [])
    invoke(plan, args)


@suppress_known_exceptions
def ps_command(
    ctx: typer.Context,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Tag filter.", autocompletion=complete_tag_names),
    ] = None,
) -> None:
    """Show running services. Named services scope the listing to those only."""
    flags, names = _compose_passthrough(ctx, None)
    resolved, plan = _plan(ctx, names, tag or [])
    invoke(plan, ["ps", *flags, *_verb_services(resolved, plan, names)])


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
    flags, names = _compose_passthrough(ctx, [service] if service else [])
    _, plan = _plan(ctx, [], [])
    args = ["logs", "--tail", str(tail)]
    if follow:
        args.append("-f")
    args.extend(flags)
    args.extend(names)
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
    """Build service images. Named services build only those — deps are not rebuilt."""
    flags, names = _compose_passthrough(ctx, services)
    resolved, plan = _plan(ctx, names, tag or [])
    args = ["build"]
    if no_cache:
        args.append("--no-cache")
    if pull:
        args.append("--pull")
    args.extend(flags)
    targets = _verb_services(resolved, plan, names)
    args.extend(targets)
    invoke(plan, args)
    _host_post(resolved, plan, "build", targets)


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
    """Pull service images. Named services pull only those — deps' images are not re-pulled."""
    flags, names = _compose_passthrough(ctx, services)
    resolved, plan = _plan(ctx, names, tag or [])
    invoke(plan, ["pull", *flags, *_verb_services(resolved, plan, names)])


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
