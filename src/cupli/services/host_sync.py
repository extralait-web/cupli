"""Lifecycle glue for host-side materialisation (bridges + exports).

Wires :mod:`cupli.services.bridge_service` and
:mod:`cupli.services.exports_service` into the compose lifecycle:

- ``pre_up`` seeds ``bind-seeded`` exports before ``docker compose up`` so the
  injected host bind is non-empty when the container starts.
- ``post_event`` runs after up / build / restart: it flags the affected
  exports stale, re-syncs the ones whose ``refresh_on`` lists the event, and
  (on ``up``) creates/repairs host_bridge symlinks.

Everything here is opt-in and guarded by :func:`applicable` — a space with no
``exports:`` and no ``host_bridge`` mounts pays nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cupli.domain.enums import ExportStrategy

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cupli.core.loader import ResolvedSpace
    from cupli.services.compose_service import CompiledPlan


def applicable(resolved: ResolvedSpace) -> bool:
    """True when the space declares any export or any host_bridge mount."""
    if resolved.space.exports:
        return True
    return any(mount.bridge_enabled for mount in resolved.space.mounts.values())


def pre_up(resolved: ResolvedSpace, plan: CompiledPlan) -> None:
    """Seed every ``bind-seeded`` export of the planned apps before ``up``."""
    if not resolved.space.exports:
        return
    apps = _target_apps(resolved, plan.services)
    names = [
        name
        for name, export in resolved.space.exports.items()
        if export.strategy is ExportStrategy.BIND_SEEDED and export.from_app in apps
    ]
    if not names:
        return
    from cupli.services.compose_service import resolved_compose_config
    from cupli.services.exports_service import sync_exports

    sync_exports(resolved, names, config=resolved_compose_config(plan))


def post_event(resolved: ResolvedSpace, plan: CompiledPlan, event: str, service_names: Sequence[str]) -> None:
    """Refresh exports (and, on ``up``, bridges) for the operated services."""
    if not applicable(resolved):
        return
    config = _read_config(plan)
    if resolved.space.exports:
        _refresh_exports(resolved, event, service_names, config)
    if event == "up":
        _refresh_bridges(resolved, config)


# --- helpers ---------------------------------------------------------------


def _refresh_exports(resolved: ResolvedSpace, event: str, service_names: Sequence[str], config: dict | None) -> None:
    """Mark affected exports stale, then sync those whose ``refresh_on`` lists ``event``."""
    from cupli.services.exports_service import mark_stale, sync_exports

    apps = _target_apps(resolved, service_names)
    for app in apps:
        mark_stale(resolved, app)
    names = [
        name
        for name, export in resolved.space.exports.items()
        if export.from_app in apps and event in {hook.value for hook in export.refresh_on}
    ]
    if names:
        sync_exports(resolved, names, config=config)


def _refresh_bridges(resolved: ResolvedSpace, config: dict | None) -> None:
    """Create/repair host_bridge symlinks; never block the lifecycle on failure."""
    from cupli.domain.errors import CupliError
    from cupli.services.bridge_service import bridge_mounts

    try:
        bridge_mounts(resolved, config=config)
    except CupliError:
        raise
    except Exception:
        return


def _read_config(plan: CompiledPlan) -> dict | None:
    """Read the merged compose config; ``None`` when docker is unavailable."""
    from cupli.services.compose_service import resolved_compose_config

    return resolved_compose_config(plan)


def _target_apps(resolved: ResolvedSpace, service_names: Sequence[str]) -> set[str]:
    """Map operated compose services to owning apps (all apps when none named)."""
    from cupli.services.compose_service import _find_owning_app

    if not service_names:
        return set(resolved.space.apps)
    apps: set[str] = set()
    for svc in service_names:
        owner = _find_owning_app(resolved, svc)
        if owner is not None:
            apps.add(owner)
    return apps


__all__ = ("applicable", "post_event", "pre_up")
