"""Host-bridge symlinks for mounts (Feature ``host_bridge``).

A mount whose ``exec_path`` lives under a hosting app's workdir bind can keep
an *inverse* symlink on the host: ``<host-equivalent of exec_path> → mount.path``.
That lets host tooling (IDEs, workspace-package resolvers) see the mounted
library at the same relative path the container uses, so relative symlinks
inside ``node_modules`` (pnpm ``@scope/<lib> → ../../packages/<lib>``) resolve
on the host too.

The host-equivalent is derived from the hosting service's bind
``source:target`` (usually ``${APP_PATH}:/app``):

    host_link = <source> + (exec_path − target)

cupli only ever touches symlinks it created (tracked in
``state/bridges.json``); a foreign non-symlink object on the link path is left
alone and surfaces as ``E032``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cupli.core.env_resolver import substitute
from cupli.domain.consts import STATE_DIR
from cupli.utils.path import create_dir, read_json, write_json

if TYPE_CHECKING:
    from cupli.core.loader import ResolvedSpace

BRIDGES_FILE = "bridges.json"
"""State file recording host_bridge symlinks cupli created (``{mount: link}``)."""


@dataclass(frozen=True)
class BridgeResult:
    """Outcome of a bridge create/repair/remove operation for one mount.

    ``status`` is one of ``ok`` / ``created`` / ``repaired`` / ``removed`` /
    ``conflict`` / ``unresolved`` / ``skipped``.
    """

    name: str
    link: Path | None
    target: Path
    status: str
    detail: str = ""


@dataclass(frozen=True)
class BridgeInfo:
    """A row for ``cupli mounts list``'s ``bridge`` column.

    ``status``: ``none`` (no host_bridge) / ``ok`` / ``broken`` / ``conflict``
    / ``pending`` (enabled but not yet created / link not derivable offline).
    """

    name: str
    status: str


# --- pure derivation -------------------------------------------------------


def derive_host_link(exec_path: str, binds: list[tuple[str, str]]) -> Path | None:
    """Return the host equivalent of ``exec_path`` given ``(source, target)`` binds.

    Picks the bind whose ``target`` is the longest strict ancestor of
    ``exec_path`` and returns ``source / (exec_path − target)``. Returns
    ``None`` when no bind contains ``exec_path``.
    """
    best: tuple[str, str] | None = None
    for source, target in binds:
        # STRICT ancestor only: a bind whose target equals exec_path is the
        # mount's own injected bind (cupli mounts the lib at exec_path), not the
        # app's workdir bind — skip it, else `rel` is empty and derivation fails.
        if exec_path.startswith(target.rstrip("/") + "/"):
            if best is None or len(target) > len(best[1]):
                best = (source, target)
    if best is None:
        return None
    source, target = best
    rel = exec_path[len(target.rstrip("/")) :].lstrip("/")
    if not rel:
        return None
    return Path(source) / rel


def binds_for_services(config: dict, service_names: set[str]) -> list[tuple[str, str]]:
    """Collect ``(source, target)`` bind pairs for the named services in a compose config."""
    out: list[tuple[str, str]] = []
    services = config.get("services") or {}
    if not isinstance(services, dict):
        return out
    for svc_name, svc in services.items():
        if svc_name not in service_names or not isinstance(svc, dict):
            continue
        out.extend(
            (str(vol["source"]), str(vol["target"]))
            for vol in (svc.get("volumes") or [])
            if isinstance(vol, dict) and vol.get("type") == "bind" and vol.get("source") and vol.get("target")
        )
    return out


def link_status(link: Path, target: Path) -> str:
    """Classify the on-disk state of a bridge link: ok/broken/empty/conflict/none.

    ``empty`` is a reclaimable docker / prior-run stub on the link path — an
    empty directory (e.g. ``packages/<lib>``) or a 0-byte regular file (e.g. a
    ``mkdocs.yml`` sub-mount point the daemon created). Both are safe to remove
    and replace with the symlink. ``conflict`` is a non-empty directory, a
    non-empty file, or a foreign symlink — never touched.
    """
    if link.is_symlink():
        try:
            points_to = (link.parent / os.readlink(link)).resolve()
        except OSError:
            return "broken"
        return "ok" if points_to == target.resolve() else "broken"
    if not link.exists():
        return "none"
    if link.is_dir():
        return "empty" if not any(link.iterdir()) else "conflict"
    if link.is_file() and link.stat().st_size == 0:
        return "empty"
    return "conflict"


# --- bridge / unbridge -----------------------------------------------------


def bridge_mounts(
    resolved: ResolvedSpace,
    names: list[str] | None = None,
    *,
    config: dict | None = None,
) -> list[BridgeResult]:
    """Create or repair host_bridge symlinks for the selected active mounts.

    ``names`` restricts to specific mounts (default: every active, bridge-
    enabled mount). ``config`` is a pre-fetched ``docker compose config`` doc
    reused for auto-derivation; when omitted and any mount needs derivation, it
    is fetched lazily.
    """
    targets = _selected_bridge_mounts(resolved, names)
    if not targets:
        return []
    owned = _read_owned(resolved)
    results: list[BridgeResult] = []
    config_loaded = config is not None
    try:
        for name in targets:
            link = _explicit_link(resolved, name)
            if link is None:
                if not config_loaded:
                    config = _fetch_config(resolved, targets)
                    config_loaded = True
                link = _derive_link(resolved, name, config)
            results.append(_apply_bridge(resolved, name, link, owned))
    finally:
        # Persist what was created even if a later mount fails — otherwise an
        # already-created symlink is orphaned (untracked) and `unbridge` cannot
        # remove it ("not cupli-owned").
        _write_owned(resolved, owned)
    return results


def unbridge_mounts(resolved: ResolvedSpace, names: list[str] | None = None) -> list[BridgeResult]:
    """Remove host_bridge symlinks cupli created for the selected mounts."""
    owned = _read_owned(resolved)
    selected = list(names) if names else sorted(owned)
    results: list[BridgeResult] = []
    for name in selected:
        stored = owned.get(name)
        target = resolved.mounts[name].path if name in resolved.mounts else Path()
        if stored is None:
            results.append(
                BridgeResult(name=name, link=None, target=target, status="skipped", detail="not cupli-owned")
            )
            continue
        link = Path(stored)
        if link.is_symlink():
            link.unlink()
            results.append(BridgeResult(name=name, link=link, target=target, status="removed"))
        else:
            results.append(BridgeResult(name=name, link=link, target=target, status="skipped", detail="not a symlink"))
        owned.pop(name, None)
    _write_owned(resolved, owned)
    return results


def bridge_info(resolved: ResolvedSpace) -> dict[str, BridgeInfo]:
    """Return per-mount bridge status for display (no docker)."""
    owned = _read_owned(resolved)
    info: dict[str, BridgeInfo] = {}
    for name, mount in resolved.space.mounts.items():
        if not mount.bridge_enabled:
            info[name] = BridgeInfo(name=name, status="none")
            continue
        link = _explicit_link(resolved, name) or (Path(owned[name]) if name in owned else None)
        if link is None:
            info[name] = BridgeInfo(name=name, status="pending")
            continue
        status = link_status(link, resolved.mounts[name].path)
        info[name] = BridgeInfo(name=name, status="pending" if status in {"none", "empty"} else status)
    return info


# --- helpers ---------------------------------------------------------------


def _selected_bridge_mounts(resolved: ResolvedSpace, names: list[str] | None) -> list[str]:
    """Return active, bridge-enabled mounts, optionally narrowed to ``names``."""
    from cupli.services.mounts_service import active_mounts

    active = active_mounts(resolved)
    candidates = [name for name, mount in resolved.space.mounts.items() if mount.bridge_enabled and name in active]
    if names is None:
        return candidates
    wanted = set(names)
    return [name for name in candidates if name in wanted]


def _explicit_link(resolved: ResolvedSpace, name: str) -> Path | None:
    """Resolve an explicit ``host_bridge.link`` for a mount, or None when auto."""
    spec = resolved.space.mounts[name].bridge_spec
    if spec.link is None:
        return None
    # abspath, not resolve(): never follow the bridge symlink itself, else a
    # second run would resolve the link to its target and lose the link path.
    return Path(os.path.abspath(substitute(spec.link, resolved.mounts[name].vars)))


def _derive_link(resolved: ResolvedSpace, name: str, config: dict | None) -> Path | None:
    """Auto-derive a mount's bridge link from its hosting services' workdir bind.

    Scopes the bind search to the services of the mount's ``hosted_in`` apps —
    NOT every service in the merged compose. Scanning all services would let an
    unrelated app's ``/app`` bind win when several apps each bind their own
    directory to the same container path, producing a host link under the wrong
    app's checkout.
    """
    if config is None:
        return None
    from cupli.services.compose_service import _managed_services

    mount = resolved.space.mounts[name]
    service_names: set[str] = set()
    for app in mount.hosted_in:
        service_names.update(_managed_services(resolved, app))
    exec_path = resolved.mounts[name].vars["MOUNT_EXEC_PATH"]
    link = derive_host_link(exec_path, binds_for_services(config, service_names))
    return Path(os.path.abspath(link)) if link is not None else None


def _fetch_config(resolved: ResolvedSpace, mount_names: list[str]) -> dict | None:
    """Build a plan over the hosting apps and read the merged compose config."""
    from cupli.services.compose_service import make_plan, resolved_compose_config

    hosts: set[str] = set()
    for name in mount_names:
        hosts.update(a for a in resolved.space.mounts[name].hosted_in if a in resolved.space.apps)
    if not hosts:
        return None
    try:
        plan = make_plan(resolved, services=sorted(hosts))
    except Exception:
        return None
    return resolved_compose_config(plan)


def _apply_bridge(resolved: ResolvedSpace, name: str, link: Path | None, owned: dict[str, str]) -> BridgeResult:
    """Create / repair one symlink; update ``owned`` in place. Pure of state I/O."""
    target = resolved.mounts[name].path
    if link is None:
        return BridgeResult(name=name, link=None, target=target, status="unresolved", detail="no hosting bind found")
    if Path(os.path.abspath(link)) == target.resolve():
        return BridgeResult(name=name, link=link, target=target, status="skipped", detail="link equals target")
    relative = resolved.space.mounts[name].bridge_spec.relative
    status = link_status(link, target)
    if status == "ok":
        owned[name] = str(link)
        return BridgeResult(name=name, link=link, target=target, status="ok")
    if status == "conflict":
        # Report as a result, not a raised error: one conflicting mount must not
        # abort the whole batch (orphaning symlinks created earlier in the loop)
        # nor break `cupli up`. The CLI surfaces a non-zero exit on conflicts.
        return BridgeResult(
            name=name, link=link, target=target, status="conflict", detail="non-empty dir, file, or foreign symlink"
        )
    action = "repaired" if status == "broken" else "created"
    try:
        _write_symlink(link, target, relative=relative)
    except (OSError, ValueError) as exc:
        # Symlink creation can be denied (e.g. Windows without the
        # create-symlink privilege) or impossible (relative link across
        # drives). Degrade instead of breaking the lifecycle.
        return BridgeResult(name=name, link=link, target=target, status="unsupported", detail=str(exc))
    owned[name] = str(link)
    return BridgeResult(name=name, link=link, target=target, status=action)


def _write_symlink(link: Path, target: Path, *, relative: bool) -> None:
    """Create (or replace a stale symlink / empty stub) ``link → target``.

    A stale symlink is unlinked; an empty directory or 0-byte file stub left by
    docker or a prior run is removed. The caller (:func:`_apply_bridge`) only
    reaches here for the ``none`` / ``broken`` / ``empty`` states, so removing
    the stub is safe.
    """
    if link.is_symlink():
        link.unlink()
    elif link.is_dir():
        link.rmdir()
    elif link.exists():
        link.unlink()
    create_dir(link.parent)
    dest = os.path.relpath(target, start=link.parent) if relative else str(target)
    os.symlink(dest, link)


def _state_path(resolved: ResolvedSpace) -> Path:
    """Return (and create) the bridges state file path."""
    state_dir = Path(resolved.space_vars["LOCALS_PATH"]) / resolved.space.name / STATE_DIR
    create_dir(state_dir)
    return state_dir / BRIDGES_FILE


def _read_owned(resolved: ResolvedSpace) -> dict[str, str]:
    """Read the ``{mount: link}`` map of cupli-created symlinks."""
    path = _state_path(resolved)
    if not path.exists():
        return {}
    raw = read_json(path)
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _write_owned(resolved: ResolvedSpace, owned: dict[str, str]) -> None:
    """Persist the ``{mount: link}`` map (sorted)."""
    write_json(_state_path(resolved), dict(sorted(owned.items())))


__all__ = (
    "BRIDGES_FILE",
    "BridgeInfo",
    "BridgeResult",
    "binds_for_services",
    "bridge_info",
    "bridge_mounts",
    "derive_host_link",
    "link_status",
    "unbridge_mounts",
)
