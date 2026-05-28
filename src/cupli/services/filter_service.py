"""Service-set selection.

Given a resolved space and a filter (explicit names, tags, or a mode), compute
the set of services to act on plus their dependency closure. Services with
``mode=disabled`` are excluded unless explicitly named.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cupli.domain.enums import DepMode, ServiceMode

if TYPE_CHECKING:
    from collections.abc import Iterable

    from cupli.core.loader import ResolvedSpace


def closure(
    resolved: ResolvedSpace,
    *,
    names: Iterable[str] = (),
    tags: Iterable[str] = (),
    mode: DepMode | None = None,
    include_disabled: bool = False,
) -> list[str]:
    """Return the dependency-closed list of service names to operate on.

    Args:
        resolved: a :class:`ResolvedSpace` from :func:`load_space`.
        names: explicit service names to seed the closure. Empty means "all".
        tags: tags to seed the closure (union with ``names``).
        mode: dep mode used to traverse ``apps[*].deps``. ``None`` keeps every
            edge.
        include_disabled: when False, apps with ``mode=disabled`` are excluded.

    Returns:
        Stable, dependency-ordered list of app names (deps appear before
        dependants).
    """
    universe = set(resolved.space.apps)
    seeds = _resolve_seeds(resolved, universe, names=names, tags=tags)
    visited = _walk_deps(resolved, seeds, mode=mode)
    ordered = _topological_sort(resolved, visited, mode=mode)
    return _filter_disabled(resolved, ordered, include_disabled=include_disabled)


def _resolve_seeds(
    resolved: ResolvedSpace,
    universe: set[str],
    *,
    names: Iterable[str],
    tags: Iterable[str],
) -> set[str]:
    """Pick the initial set of service names from explicit names + tags."""
    explicit = set(names) & universe
    tag_set = set(tags)
    if tag_set:
        explicit |= {app_name for app_name, app in resolved.space.apps.items() if tag_set & set(app.tags)}
    if not explicit and not tag_set:
        return universe
    return explicit


def _walk_deps(
    resolved: ResolvedSpace,
    seeds: set[str],
    *,
    mode: DepMode | None,
) -> set[str]:
    """Breadth-first traversal across mode-tagged ``apps[*].deps`` edges."""
    visited: set[str] = set()
    pending = list(seeds)
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        for dep_name, dep_spec in resolved.space.apps[current].deps.items():
            if mode is not None and DepMode(mode) not in dep_spec.modes:
                continue
            if dep_name not in visited:
                pending.append(dep_name)
    return visited


def _topological_sort(
    resolved: ResolvedSpace,
    nodes: set[str],
    *,
    mode: DepMode | None,
) -> list[str]:
    """Order ``nodes`` so that dependencies precede dependants (stable)."""
    ordered: list[str] = []
    pending: set[str] = set(nodes)
    while pending:
        ready = _ready_nodes(resolved, pending, mode=mode)
        if not ready:
            # Dependency cycle within the selected subset — fall back to
            # declaration order so we still produce a result.
            ordered.extend(name for name in resolved.space.apps if name in pending)
            return ordered
        for name in sorted(ready):
            ordered.append(name)
            pending.discard(name)
    return ordered


def _ready_nodes(
    resolved: ResolvedSpace,
    pending: set[str],
    *,
    mode: DepMode | None,
) -> set[str]:
    """Nodes in ``pending`` whose deps are not still in ``pending``."""
    return {
        name
        for name in pending
        if all(
            dep not in pending
            for dep, dep_spec in resolved.space.apps[name].deps.items()
            if mode is None or DepMode(mode) in dep_spec.modes
        )
    }


def _filter_disabled(
    resolved: ResolvedSpace,
    ordered: list[str],
    *,
    include_disabled: bool,
) -> list[str]:
    """Drop ``mode=disabled`` apps unless ``include_disabled`` is True."""
    if include_disabled:
        return ordered
    return [name for name in ordered if resolved.space.apps[name].mode is not ServiceMode.DISABLED]


__all__ = ("closure",)
