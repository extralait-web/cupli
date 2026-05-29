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


def prepare_up(resolved: ResolvedSpace, plan: CompiledPlan) -> None:
    """Prepare the host + docker state before ``up`` so a fresh deploy is clean.

    Three steps, all gated by :func:`_needs_prepare` (zero cost otherwise) and
    best-effort (never block ``up``):

    1. Build any image needed below that is missing — so a fresh deploy seeds /
       initialises from a real image rather than an empty bind / volume.
    2. Initialise shared named volumes once, serially (avoids the concurrent
       ``up`` init race when several services share one fresh volume).
    3. Seed ``bind-seeded`` exports from the (now-present) image, so the
       container starts with a populated host bind instead of running a slow,
       network-bound package install at runtime.
    """
    if not _needs_prepare(resolved):
        return
    from cupli.services.compose_service import ensure_images, prepare_shared_volumes, resolved_compose_config

    config = resolved_compose_config(plan)
    if config is None:
        return
    ensure_images(plan, _images_for_prep(resolved, config))
    prepare_shared_volumes(config)
    _seed_bind_exports(resolved, plan, config)


def _needs_prepare(resolved: ResolvedSpace) -> bool:
    """True when a space needs pre-``up`` prep: bind-seeded exports or a compound app."""
    from cupli.domain.enums import ExportStrategy
    from cupli.services.compose_service import _managed_services

    if any(export.strategy is ExportStrategy.BIND_SEEDED for export in resolved.space.exports.values()):
        return True
    # A compound app (≥2 compose services) may share a named volume → H2 race risk.
    return any(len(_managed_services(resolved, app)) >= 2 for app in resolved.space.apps)


def _images_for_prep(resolved: ResolvedSpace, config: dict) -> dict[str, str]:
    """Map ``service -> image`` for services that prep needs an image present for.

    Covers services sharing a named volume (volume init) and the owning services
    of bind-seeded exports with an empty host (seed copy).
    """
    from cupli.services.exports_service import _is_populated, _owning_services

    services = config.get("services") or {}
    top = config.get("volumes") or {}
    by_volume: dict[str, dict[str, str]] = {}
    for svc_name, svc in services.items():
        image = svc.get("image") if isinstance(svc, dict) else None
        if not image:
            continue
        for vol in svc.get("volumes") or []:
            if isinstance(vol, dict) and vol.get("type") == "volume" and vol.get("source") and vol.get("target"):
                real = str((top.get(str(vol["source"])) or {}).get("name", vol["source"]))
                by_volume.setdefault(real, {})[svc_name] = str(image)
    want: dict[str, str] = {}
    for per_service in by_volume.values():
        if len(per_service) >= 2:
            want.update(per_service)
    for name, export in resolved.space.exports.items():
        if export.strategy is ExportStrategy.BIND_SEEDED and not _is_populated(resolved.exports[name].path):
            for svc in _owning_services(resolved, export.from_app):
                image = (services.get(svc) or {}).get("image")
                if image:
                    want[svc] = str(image)
    return want


def _seed_bind_exports(resolved: ResolvedSpace, plan: CompiledPlan, config: dict | None) -> None:
    """Seed every ``bind-seeded`` export of the planned apps from the image."""
    apps = _target_apps(resolved, plan.services)
    names = [
        name
        for name, export in resolved.space.exports.items()
        if export.strategy is ExportStrategy.BIND_SEEDED and export.from_app in apps
    ]
    if not names:
        return
    from cupli.services.exports_service import sync_exports

    sync_exports(resolved, names, config=config)


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
    """Create/repair host_bridge symlinks; never block the lifecycle.

    ``bridge_mounts`` reports conflicts as results (it does not raise), so a
    foreign object on one link path can't break ``cupli up``. Any unexpected
    error is swallowed — bridges are a convenience, not a lifecycle gate.
    """
    from cupli.services.bridge_service import bridge_mounts

    try:
        bridge_mounts(resolved, config=config)
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


__all__ = ("applicable", "post_event", "prepare_up")
