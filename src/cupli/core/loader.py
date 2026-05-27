"""Space loader.

Wraps :func:`cupli.core.parser.parse_space_file` and resolves the variable
chains and default paths described in §7f of the v2 plan. The output is a
fully-resolved :class:`ResolvedSpace` that downstream services can consume
without re-reading the YAML file.

This module performs NO side effects beyond reading env files referenced by
the space. Filesystem mutation (clone, post_clone) lives in
``services/workspace_service.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from cupli.core import registry
from cupli.core.c3 import c3_linearise
from cupli.core.env_resolver import (
    check_no_shadow,
    filter_process_env,
    load_env_file,
    merge_scopes,
    substitute,
)
from cupli.core.parser import parse_space_file
from cupli.domain.consts import (
    DEFAULT_APPS_DIR,
    DEFAULT_BASES_DIR,
    DEFAULT_LOCALS_DIR,
    DEFAULT_MOUNTS_DIR,
)
from cupli.domain.errors import CupliError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from cupli.domain.models import AppModel, BaseAppModel, MountModel, SpaceModel
    from cupli.domain.plan import LineMarks


SPACE_RESERVED: frozenset[str] = frozenset(
    (
        "SPACE_NAME",
        "SPACE_PATH",
        "APPS_DIR",
        "APPS_PATH",
        "BASES_DIR",
        "BASES_PATH",
        "MOUNTS_DIR",
        "MOUNTS_PATH",
        "LOCALS_DIR",
        "LOCALS_PATH",
        "NETWORK",
        "COMPOSE_PROJECT_NAME",
    )
)
"""Reserved variable names exported by the space-scope auto-vars step."""

COMPONENT_RESERVED: frozenset[str] = frozenset(("APP_NAME", "APP_PATH", "APP_LOCAL_PATH"))
"""Reserved variable names exported by apps and bases."""

MOUNT_RESERVED: frozenset[str] = frozenset(("MOUNT_NAME", "MOUNT_PATH", "MOUNT_HOST", "MOUNT_EXEC_PATH"))
"""Reserved variable names exported by mounts."""


@dataclass(frozen=True)
class ResolvedComponent:
    """Per-app / per-base / per-mount resolved view.

    Attributes:
        name: declared key in the space.
        path: absolute resolved working directory on the host.
        vars: full scope visible to the component (auto-vars + env files +
            user vars, merged with everything above it in the inheritance
            chain). Use this when you need to substitute paths or evaluate
            expressions that reference auto-vars.
        container_vars: subset of ``vars`` that should be injected into the
            running container's environment. Auto-vars (``SPACE_*`` / ``APP_*``
            / ``MOUNT_*`` / process-env forwards) are filtered out — only what
            the user explicitly declared in ``vars:`` / ``envs:`` survives.
    """

    name: str
    path: Path
    vars: dict[str, str] = field(default_factory=dict)
    container_vars: dict[str, str] = field(default_factory=dict)
    ports: tuple[str, ...] = ()
    """Compose-style port mappings with ``${VAR}`` references substituted."""


@dataclass(frozen=True)
class ResolvedSpace:
    """Fully-resolved view of a space file.

    Attributes:
        space: validated :class:`SpaceModel`.
        space_dir: absolute directory containing the space file.
        space_vars: resolved space-scope variables (includes auto-vars).
        bases: resolved base components.
        apps: resolved app components.
        mounts: resolved mount components.
        marks: optional line/column map from the parser.
    """

    space: SpaceModel
    space_dir: Path
    space_vars: dict[str, str] = field(default_factory=dict)
    bases: dict[str, ResolvedComponent] = field(default_factory=dict)
    apps: dict[str, ResolvedComponent] = field(default_factory=dict)
    mounts: dict[str, ResolvedComponent] = field(default_factory=dict)
    marks: LineMarks | None = None


def load_space(
    space_path: Path,
    *,
    strict_vars: bool = False,
    allow_shadow: bool = False,
    auto_register: bool = True,
    auto_cache: bool = True,
) -> ResolvedSpace:
    """Parse + resolve a space file.

    Args:
        space_path: absolute path to ``space.cupli.yaml``.
        strict_vars: when True, unknown ``${VAR}`` references raise ``E016``.
        allow_shadow: when True, user variables may reuse reserved auto-var
            names without raising ``E015``.
        auto_register: when True (default), an unknown space whose ``name`` is
            free in the registry is silently added — so a fresh checkout starts
            participating in ``cupli workspace list`` after the first command.
        auto_cache: when True (default), the resolved ``commands:`` block is
            persisted to ``~/.cache/cupli/<space>/cache.json`` so the next
            ``cupli`` invocation can register dynamic shortcuts at top level
            (see :func:`cupli.cli.root._register_workspace_shortcuts`).

    Returns:
        Fully-resolved :class:`ResolvedSpace`.
    """
    space, marks = parse_space_file(space_path)
    space_dir = space_path.parent.resolve()
    space_vars = _resolve_space_scope(
        space=space,
        space_dir=space_dir,
        strict=strict_vars,
        allow_shadow=allow_shadow,
    )
    # Inject default component path-vars (<NAME>_APP_PATH / _BASE_PATH / _MOUNT_PATH)
    # so user YAML may reference siblings before each component's own resolve
    # (two-pass: defaults computed here, custom ``path:`` resolved later in
    # ``_resolve_component`` against the enriched scope).
    space_vars = {**space_vars, **_default_path_vars(space, space_vars)}
    bases = _resolve_bases(space, space_vars, strict=strict_vars, allow_shadow=allow_shadow)
    apps = _resolve_apps(space, bases, space_vars, strict=strict_vars, allow_shadow=allow_shadow)
    mounts = _resolve_mounts(space, space_vars, strict=strict_vars, allow_shadow=allow_shadow)
    if auto_register:
        _try_auto_register(space.name, space_path.resolve())
    if auto_cache:
        _try_write_cache(space, space_path.resolve())
    return ResolvedSpace(
        space=space,
        space_dir=space_dir,
        space_vars=space_vars,
        bases=bases,
        apps=apps,
        mounts=mounts,
        marks=marks,
    )


def _try_write_cache(space, path: Path) -> None:
    """Persist ``commands:`` to the per-space cache file. Failures are silent."""
    try:
        from cupli.core import cache

        cache.write_commands(path, space.name, space.commands)
    except (OSError, ValueError):
        pass


def _try_auto_register(name: str, path: Path) -> None:
    """Register ``(name, path)`` in the registry when the name is free.

    A pre-existing entry is left alone (regardless of whether its path
    matches). Any registry error is swallowed — auto-registration must
    never break a load.
    """
    try:
        known = registry.list_known_spaces()
    except CupliError:
        return
    if name in known:
        return
    try:
        registry.add_space(name, path)
    except CupliError:
        return


# --- space scope -----------------------------------------------------------


def _resolve_space_scope(
    *,
    space: SpaceModel,
    space_dir: Path,
    strict: bool,
    allow_shadow: bool,
) -> dict[str, str]:
    """Compute the space-scope variable set."""
    auto = _space_auto_vars(space, space_dir)
    env_layers = [_load_declared_env(_resolve_path(item, auto, space_dir), strict=strict) for item in space.envs]
    if not allow_shadow:
        check_no_shadow(space.vars, SPACE_RESERVED)
    return merge_scopes(
        [filter_process_env(), auto, *env_layers, dict(space.vars)],
        strict=strict,
    )


def _default_path_vars(space: SpaceModel, space_vars: dict[str, str]) -> dict[str, str]:
    """Pre-compute ``<NAME>_{APP,BASE,MOUNT}_PATH`` for every declared component.

    First pass of the path-var two-pass scheme: every component is mapped to
    its **default** on-disk path (``<APPS_PATH>/<name>`` etc.), regardless of
    whether the component declares its own ``path:``. User YAML may reference
    these freely (``apps.celery.path: ${BACKEND_APP_PATH}``); a custom ``path:``
    cannot transitively reference another custom ``path:`` by design — it sees
    only sibling defaults.
    """
    out: dict[str, str] = {}
    apps_root = Path(space_vars["APPS_PATH"])
    bases_root = Path(space_vars["BASES_PATH"])
    mounts_root = Path(space_vars["MOUNTS_PATH"])
    for name in space.apps:
        out[f"{_to_env_ident(name)}_APP_PATH"] = str(apps_root / name)
    for name in space.bases:
        out[f"{_to_env_ident(name)}_BASE_PATH"] = str(bases_root / name)
    for name in space.mounts:
        out[f"{_to_env_ident(name)}_MOUNT_PATH"] = str(mounts_root / name)
    return out


def _to_env_ident(name: str) -> str:
    """Upper-case ``name`` with ``-`` mapped to ``_`` for use as a shell id."""
    return name.upper().replace("-", "_")


def _space_auto_vars(space: SpaceModel, space_dir: Path) -> dict[str, str]:
    """Return SPACE_*/APPS_PATH/BASES_PATH/MOUNTS_PATH/LOCALS_PATH/NETWORK auto-vars."""
    return {
        "SPACE_NAME": space.name,
        "SPACE_PATH": str(space_dir),
        "APPS_DIR": DEFAULT_APPS_DIR,
        "APPS_PATH": str(space_dir / DEFAULT_APPS_DIR),
        "BASES_DIR": DEFAULT_BASES_DIR,
        "BASES_PATH": str(space_dir / DEFAULT_BASES_DIR),
        "MOUNTS_DIR": DEFAULT_MOUNTS_DIR,
        "MOUNTS_PATH": str(space_dir / DEFAULT_MOUNTS_DIR),
        "LOCALS_DIR": DEFAULT_LOCALS_DIR,
        "LOCALS_PATH": str(space_dir / DEFAULT_LOCALS_DIR),
        "NETWORK": space.name,
        "COMPOSE_PROJECT_NAME": space.name,
    }


# --- bases / apps / mounts -------------------------------------------------


def _resolve_bases(
    space: SpaceModel,
    space_vars: dict[str, str],
    *,
    strict: bool,
    allow_shadow: bool,
) -> dict[str, ResolvedComponent]:
    """Resolve every declared base."""
    return {
        name: _resolve_component(
            name=name,
            component=base,
            outer=space_vars,
            default_root=space_vars["BASES_PATH"],
            strict=strict,
            allow_shadow=allow_shadow,
        )
        for name, base in space.bases.items()
    }


def _resolve_apps(
    space: SpaceModel,
    bases: dict[str, ResolvedComponent],
    space_vars: dict[str, str],
    *,
    strict: bool,
    allow_shadow: bool,
) -> dict[str, ResolvedComponent]:
    """Resolve every declared app, applying C3-linearised bases."""
    resolved: dict[str, ResolvedComponent] = {}
    for name, app in space.apps.items():
        base_chain = c3_linearise(space, name)
        base_vars = (bases[base].vars for base in base_chain if base in bases)
        outer = merge_scopes([space_vars, *base_vars], strict=strict)
        resolved[name] = _resolve_component(
            name=name,
            component=app,
            outer=outer,
            default_root=space_vars["APPS_PATH"],
            strict=strict,
            allow_shadow=allow_shadow,
            extra_auto={"APP_LOCAL_PATH": str(Path(space_vars["LOCALS_PATH"]) / name)},
        )
    return resolved


def _resolve_mounts(
    space: SpaceModel,
    space_vars: dict[str, str],
    *,
    strict: bool,
    allow_shadow: bool,
) -> dict[str, ResolvedComponent]:
    """Resolve every declared mount."""
    return {
        name: _resolve_mount(
            name=name,
            mount=mount,
            outer=space_vars,
            strict=strict,
            allow_shadow=allow_shadow,
        )
        for name, mount in space.mounts.items()
    }


def _resolve_component(
    *,
    name: str,
    component: AppModel | BaseAppModel,
    outer: dict[str, str],
    default_root: str,
    strict: bool,
    allow_shadow: bool,
    extra_auto: dict[str, str] | None = None,
) -> ResolvedComponent:
    """Resolve auto-vars, envs, and vars for an app or base component."""
    path = _resolve_component_path(component, outer, name, default_root)
    auto: dict[str, str] = {
        "APP_NAME": name,
        "APP_PATH": str(path),
    }
    if extra_auto:
        auto.update(extra_auto)
    env_layers = [_load_declared_env(_resolve_path(item, outer | auto, path), strict=strict) for item in component.envs]
    if not allow_shadow:
        check_no_shadow(component.vars, COMPONENT_RESERVED)
    scope = merge_scopes([outer, auto, *env_layers, dict(component.vars)], strict=strict)
    container_vars = _container_subset(scope, auto)
    ports = _resolve_ports(getattr(component, "ports", ()), scope, strict=strict)
    return ResolvedComponent(
        name=name,
        path=path,
        vars=scope,
        container_vars=container_vars,
        ports=ports,
    )


def _resolve_ports(raw_ports: Iterable[str], scope: dict[str, str], *, strict: bool) -> tuple[str, ...]:
    """Substitute ``${VAR}`` references inside ``ports:`` entries."""
    return tuple(substitute(entry, scope, strict=strict) for entry in raw_ports)


def _resolve_mount(
    *,
    name: str,
    mount: MountModel,
    outer: dict[str, str],
    strict: bool,
    allow_shadow: bool,
) -> ResolvedComponent:
    """Resolve auto-vars, envs, and vars for a mount component."""
    default_root = outer["MOUNTS_PATH"]
    path = _resolve_component_path(mount, outer, name, default_root)
    exec_path = substitute(mount.exec_path, outer, strict=strict)
    auto = {
        "MOUNT_NAME": name,
        "MOUNT_PATH": str(path),
        "MOUNT_HOST": str(path),
        "MOUNT_EXEC_PATH": exec_path,
    }
    env_layers = [_load_declared_env(_resolve_path(item, outer | auto, path), strict=strict) for item in mount.envs]
    if not allow_shadow:
        check_no_shadow(mount.vars, MOUNT_RESERVED)
    scope = merge_scopes([outer, auto, *env_layers, dict(mount.vars)], strict=strict)
    container_vars = _container_subset(scope, auto)
    return ResolvedComponent(name=name, path=path, vars=scope, container_vars=container_vars)


_PATH_VAR_SUFFIXES: tuple[str, ...] = ("_APP_PATH", "_BASE_PATH", "_MOUNT_PATH")
"""Path-var name suffixes generated by :func:`_default_path_vars` — stripped from container env."""


def _container_subset(scope: dict[str, str], local_auto: dict[str, str]) -> dict[str, str]:
    """Strip auto-vars and forwarded process-env keys from ``scope``.

    What remains is the user-declared subset (space.vars + base.vars +
    app.vars / mount.vars + env-file values), which is what we want to expose
    inside the container — host paths like ``SPACE_PATH`` shouldn't leak.

    Per-component path-vars (``<NAME>_APP_PATH`` / ``_BASE_PATH`` / ``_MOUNT_PATH``)
    are also dropped: they exist for YAML cross-references and the ``--env-file``
    that docker compose substitutes, not for the running container.
    """
    from cupli.core.env_resolver import DEFAULT_ENV_ALLOWLIST

    excluded = (
        SPACE_RESERVED | COMPONENT_RESERVED | MOUNT_RESERVED | frozenset(DEFAULT_ENV_ALLOWLIST) | frozenset(local_auto)
    )
    return {key: value for key, value in scope.items() if key not in excluded and not _is_path_var(key)}


def _is_path_var(key: str) -> bool:
    """True when ``key`` looks like a cupli-generated path-var name."""
    return any(key.endswith(suffix) for suffix in _PATH_VAR_SUFFIXES)


def _resolve_component_path(
    component: AppModel | BaseAppModel | MountModel,
    scope: dict[str, str],
    name: str,
    default_root: str,
) -> Path:
    """Return the absolute on-disk path for a component."""
    declared = component.path
    if declared:
        return Path(substitute(declared, scope)).resolve()
    return (Path(default_root) / name).resolve()


def _resolve_path(value: str, scope: dict[str, str], anchor: Path | str) -> Path:
    """Substitute variables in ``value`` and absolutize against ``anchor``."""
    expanded = substitute(value, scope)
    candidate = Path(expanded)
    if candidate.is_absolute():
        return candidate
    return (Path(anchor) / candidate).resolve()


def _load_declared_env(path: Path, *, strict: bool) -> dict[str, str]:
    """Load a declared ``envs:`` file into the scope; empty when it is missing.

    A declared env file is loaded into the component scope and (unless it
    shadows a reserved name) injected into the container environment. Relative
    paths resolve against the component's own directory, not the space root —
    a common cause of an env file "not taking effect".

    A missing file is loaded as an empty layer. Optional files (``.env.local``)
    legitimately may not exist, so this is silent by default; under
    ``--strict-vars`` it warns to surface a misplaced path.
    """
    if not path.exists():
        if strict:
            from cupli.utils.console import warn

            warn(f"declared env file not found, skipped: {path}")
        return {}
    return load_env_file(path)


__all__ = (
    "COMPONENT_RESERVED",
    "MOUNT_RESERVED",
    "ResolvedComponent",
    "ResolvedSpace",
    "SPACE_RESERVED",
    "load_space",
)
