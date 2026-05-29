"""Compose service: render overrides, build invocation, run docker compose.

Override generation splits into two files:

- ``docker-compose.pre.yml`` (merged BEFORE user compose files): injects defaults
  that user files may override — the shared network plus any top-level
  ``volumes`` / ``secrets`` / ``configs`` blocks declared in the space.
- ``docker-compose.post.yml`` (merged AFTER user compose files): injects forced
  values — mount volumes per hosted_in service, cross-file ``depends_on``.

The ``-f`` ordering passed to docker compose is therefore:

    docker-compose.pre.yml  → base composes  → app composes  → docker-compose.post.yml
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

from cupli.domain.consts import (
    AUTO_GENERATED_HEADER,
    OVERRIDE_ENV_FILE,
    OVERRIDE_INLINE_FILE,
    OVERRIDE_POST_FILE,
    OVERRIDE_PRE_FILE,
    STATE_DIR,
)
from cupli.domain.enums import ServiceMode
from cupli.domain.errors import CupliError
from cupli.services.filter_service import closure
from cupli.utils.path import create_dir, write_text
from cupli.utils.subprocess import run_command

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from subprocess import CompletedProcess

    from cupli.core.loader import ResolvedSpace
    from cupli.domain.enums import DepMode


COMPOSE_PATH_SEP = ";" if os.name == "nt" else ":"
"""Separator used inside ``COMPOSE_FILE``; mirrors docker compose's default."""


@dataclass(frozen=True)
class CompiledPlan:
    """Pre-computed compose invocation context.

    Attributes:
        project_name: ``--project-name`` value (defaults to the space name).
        project_dir: ``--project-directory`` for compose.
        env_file: optional ``--env-file`` path.
        compose_files: ``-f`` files in merge order.
        services: services to operate on, dependency-ordered.
    """

    project_name: str
    project_dir: Path
    env_file: Path | None
    compose_files: tuple[Path, ...]
    services: tuple[str, ...] = field(default_factory=tuple)


# --- render ----------------------------------------------------------------


def render_overrides(
    resolved: ResolvedSpace,
    selected: Sequence[str] | None = None,
) -> tuple[Path, Path, Path | None]:
    """Write the generated override files to the state dir.

    Produces:

    - ``docker-compose.pre.yml`` — defaults (network, container_name) and
      top-level ``volumes`` / ``secrets`` / ``configs`` blocks.
    - ``docker-compose.post.yml`` — cupli injections (env / ports / mounts / deps / networks).
    - ``docker-compose.inline.yml`` — services declared inline under
      ``apps.<x>.services.<y>`` with extra compose-syntax fields (omitted
      when no app uses inline syntax).

    When ``selected`` is given, the overrides only mention services owned by
    those apps. This keeps ``docker compose`` from seeing stub services (just
    ``container_name``) for apps whose compose-fragments are not in the
    current ``-f`` chain — e.g. when ``--tag`` narrows the plan.

    Returns ``(pre, post, inline_or_None)``.
    """
    state_dir = _state_dir(resolved)
    pre_path = state_dir / OVERRIDE_PRE_FILE
    post_path = state_dir / OVERRIDE_POST_FILE
    inline_path = state_dir / OVERRIDE_INLINE_FILE

    scope = list(selected) if selected is not None else list(resolved.space.apps)

    inline_doc = _build_override_inline(resolved, scope)
    declared_from_files = _collect_declared_services(resolved, scope)
    declared_from_inline = set((inline_doc.get("services") or {}).keys())
    declared = declared_from_files | declared_from_inline

    pre = _build_override_pre(resolved, declared)
    post = _build_override_post(resolved, declared)
    write_text(pre_path, AUTO_GENERATED_HEADER + yaml.safe_dump(pre, sort_keys=False))
    write_text(post_path, AUTO_GENERATED_HEADER + yaml.safe_dump(post, sort_keys=False))

    if inline_doc.get("services"):
        write_text(inline_path, AUTO_GENERATED_HEADER + yaml.safe_dump(inline_doc, sort_keys=False))
        return pre_path, post_path, inline_path
    if inline_path.exists():
        inline_path.unlink()
    return pre_path, post_path, None


def _build_override_inline(resolved: ResolvedSpace, scope: Sequence[str]) -> dict:
    """Aggregate inline compose-spec from each scoped app's ``service:`` / ``services:`` entries.

    Inline sources:

    - ``apps.<x>.service: { image, build, … }`` — single-service shorthand.
      Compose service name defaults to the app's name.
    - ``apps.<x>.services.<y>: { … }`` — explicit multi-service map.

    Cupli-only keys (``vars``, ``ports``) are stripped here — they're handled
    by post-override injections. Everything else (``image``, ``build``,
    ``command``, ``environment``, ``volumes``, ``depends_on``, …) is written
    verbatim. ``${VAR}`` refs are left for docker compose to substitute from
    ``override.env``.

    ``scope`` restricts iteration to a subset of apps so the override only
    declares services from the currently selected plan.
    """
    services: dict[str, dict] = {}
    for app_name in scope:
        app = resolved.space.apps[app_name]
        for svc_name, override in _iter_inline_services(app_name, app):
            spec = override.compose_spec
            if not spec:
                continue
            block = services.setdefault(svc_name, {})
            block.update(spec)
    if not services:
        return {}
    return {"services": services}


def _iter_inline_services(app_name: str, app):
    """Yield ``(service_name, ServiceOverride)`` for every inline service of an app."""
    from cupli.domain.models import ServiceOverride

    if app.services:
        yield from app.services.items()
    elif isinstance(app.service, ServiceOverride):
        yield app_name, app.service


def write_env_file(resolved: ResolvedSpace) -> Path:
    """Write the ``override.env`` file for ``--env-file`` and return its path.

    The file contains:

    - every space-scope variable (auto-vars + ``space.vars`` + space ``envs:``);
    - per-component ``<NAME>_APP_PATH`` / ``<NAME>_MOUNT_PATH`` /
      ``<NAME>_BASE_PATH`` pointing at each component's resolved on-disk path.

    Process-env forwards (``PATH``, ``HOME``, ``USER``, …) are pulled into the
    cupli scope so YAML can substitute ``${HOME}`` etc., but are stripped
    here — docker compose inherits them from the parent shell, and putting
    them in ``--env-file`` would shadow the caller's real values.

    Per-component vars let compose-fragments reference siblings by name
    without baking absolute paths in: e.g. ``context: ${SHOP_API_APP_PATH}``.
    """
    from cupli.core.env_resolver import DEFAULT_ENV_ALLOWLIST

    state_dir = _state_dir(resolved)
    env_path = state_dir / OVERRIDE_ENV_FILE
    space_vars = {key: value for key, value in resolved.space_vars.items() if key not in DEFAULT_ENV_ALLOWLIST}
    payload = {**space_vars, **_per_component_path_vars(resolved)}
    body = "\n".join(f"{key}={value}" for key, value in payload.items())
    write_text(env_path, AUTO_GENERATED_HEADER + body + "\n")
    return env_path


def _per_component_path_vars(resolved: ResolvedSpace) -> dict[str, str]:
    """Build the ``<NAME>_{APP,MOUNT,BASE}_PATH`` env-var dict.

    Maps every component to its **actual** resolved on-disk path — so when
    a component declares a custom ``path:``, the env-var here reflects that
    override (loader's default ``_default_path_vars`` placed only the
    pre-resolve defaults into ``space_vars`` for safe YAML cross-references).

    Component names are upper-cased with ``-`` mapped to ``_`` so the result
    is a valid shell identifier. Collisions across components raise ``E030``.
    """
    groups: list[tuple[str, dict[str, Path]]] = [
        ("APP", {name: comp.path for name, comp in resolved.apps.items()}),
        ("MOUNT", {name: comp.path for name, comp in resolved.mounts.items()}),
        ("BASE", {name: comp.path for name, comp in resolved.bases.items()}),
        ("EXPORT", {name: comp.path for name, comp in resolved.exports.items()}),
    ]
    produced: dict[str, str] = {}
    sources: dict[str, list[str]] = {}
    for suffix, components in groups:
        for name, path in components.items():
            var = f"{_to_env_ident(name)}_{suffix}_PATH"
            sources.setdefault(var, []).append(f"{suffix.lower()}:{name}")
            produced[var] = str(path)
    _check_path_var_collisions(sources)
    return produced


def _to_env_ident(name: str) -> str:
    """Upper-case ``name`` with ``-`` mapped to ``_`` for use as a shell id."""
    return name.upper().replace("-", "_")


def _check_path_var_collisions(sources: dict[str, list[str]]) -> None:
    """Raise ``E030`` when two components produce the same env-var name."""
    for var, names in sources.items():
        if len(names) > 1:
            raise CupliError("E030", var=var, names=", ".join(names))


def _state_dir(resolved: ResolvedSpace) -> Path:
    """Return (and create) the per-space state directory."""
    from pathlib import Path as _Path

    locals_path = resolved.space_vars["LOCALS_PATH"]
    state_dir = _Path(locals_path) / resolved.space.name / STATE_DIR
    create_dir(state_dir)
    return state_dir


def _default_container_name(project: str, service: str) -> str:
    """Return the default container name for ``service`` in ``project``.

    ``<project>-<service>`` unless ``service`` already equals the project or
    starts with ``<project>-`` — that avoids double-prefixed names like
    ``shop-shop-api`` when a compose-fragment already qualified its services.
    """
    if service == project or service.startswith(f"{project}-"):
        return service
    return f"{project}-{service}"


def _build_override_pre(resolved: ResolvedSpace, declared: set[str]) -> dict:
    """Build the pre-override document (defaults user files may override).

    Provides:

    - ``networks.default`` mapped to the workspace's project network, alongside
      any user-declared networks from ``space.networks:`` (compose-spec
      verbatim). ``default`` wins on key collision so cupli's auto-attach stays
      predictable.
    - ``volumes`` / ``secrets`` / ``configs`` top-level blocks copied verbatim
      from the space (no synthetic default; omitted entirely when empty).
    - ``services.<svc>.container_name`` defaulted to ``<space>-<svc>`` for every
      declared service. Compose merge resolves scalar conflicts to the *last*
      file, so any ``container_name`` in a user compose-fragment wins.
    """
    project = resolved.space.name
    services = {svc: {"container_name": _default_container_name(project, svc)} for svc in sorted(declared)}
    document: dict = {"networks": _pre_networks(resolved)}
    _add_top_level_blocks(document, resolved)
    if services:
        document["services"] = services
    return document


def _pre_networks(resolved: ResolvedSpace) -> dict[str, dict]:
    """Build the ``networks`` block: user-declared verbatim plus auto ``default``."""
    networks: dict[str, dict] = {name: dict(spec) for name, spec in resolved.space.networks.items()}
    networks["default"] = {"name": resolved.space_vars["NETWORK"], "external": False}
    return networks


def _add_top_level_blocks(document: dict, resolved: ResolvedSpace) -> None:
    """Copy ``volumes`` / ``secrets`` / ``configs`` into the document verbatim.

    Each block is emitted only when the space declares at least one entry, so
    an absent block never appears as an empty ``volumes: {}`` in the output.
    """
    blocks = (
        ("volumes", resolved.space.volumes),
        ("secrets", resolved.space.secrets),
        ("configs", resolved.space.configs),
    )
    for key, source in blocks:
        if not source:
            continue
        document[key] = {name: dict(spec) for name, spec in source.items()}


def _build_override_post(resolved: ResolvedSpace, declared: set[str]) -> dict:
    """Build the post-override document.

    Five things happen here, in order:

    1. ``services.<svc>.environment`` is populated from each app's
       ``container_vars`` — that's how per-app ``vars:`` actually reach the
       running container.
    2. ``services.<svc>.ports`` from each app's resolved ``ports:`` block.
    3. ``services.<svc>.volumes`` entries are added for every active mount.
    4. ``services.<svc>.depends_on`` is added from cross-file ``deps:``.
    5. ``services.<svc>.networks`` is set to ``[default]`` for every declared
       service so compose's auto-attach behaviour stays in effect even when a
       user compose-fragment already pins one or more custom networks.

    Inject calls skip apps whose compose-service name is not declared in any
    compose-fragment — otherwise the override would create a shadow service
    without ``image`` / ``build`` and ``docker compose config`` would reject
    the merged document.
    """
    services: dict[str, dict] = {}
    _inject_service_environment(resolved, services, declared)
    _inject_service_ports(resolved, services, declared)
    _inject_mount_volumes(resolved, services, declared)
    _inject_export_binds(resolved, services, declared)
    _inject_cross_file_deps(resolved, services, declared)
    _inject_default_networks(declared, services)
    return {"services": services} if services else {}


def _collect_declared_services(resolved: ResolvedSpace, scope: Sequence[str]) -> set[str]:
    """Parse compose-fragments referenced by scoped apps and collect service names.

    Uses ``yaml.safe_load`` on each file (``${VAR}`` already substituted by
    :func:`_expand_paths`'s logic). Unreadable / non-YAML / non-mapping files
    are skipped silently — strict validation happens later via
    ``docker compose config``. Bases are restricted to those included by the
    scoped apps so an unselected app's base does not leak its services in.
    """
    declared: set[str] = set()
    base_chain = _ordered_base_chain(resolved, list(scope))
    for base_name in base_chain:
        base = resolved.space.bases[base_name]
        for path in _expand_paths(base.composes, resolved.bases[base_name].vars):
            declared.update(_services_in_compose(path))
    for app_name in scope:
        app = resolved.space.apps[app_name]
        for path in _expand_paths(app.composes, resolved.apps[app_name].vars):
            declared.update(_services_in_compose(path))
    return declared


def _services_in_compose(path: Path) -> set[str]:
    """Best-effort parse of a single compose-fragment; return its service names."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return set()
    if not isinstance(doc, dict):
        return set()
    services = doc.get("services") or {}
    if not isinstance(services, dict):
        return set()
    return set(services.keys())


def _inject_service_ports(resolved: ResolvedSpace, services: dict, declared: set[str]) -> None:
    """Add ``services.<svc>.ports`` for every compose service managed by an app.

    Per-service ``ports`` (from ``apps.<name>.services.<svc>.ports``) replaces
    the app-level list when present (set to ``[]`` to opt out).
    """
    for app_name in resolved.space.apps:
        app_ports = list(resolved.apps[app_name].ports)
        for svc_name, override in _managed_services(resolved, app_name).items():
            if svc_name not in declared:
                continue
            effective = list(override.ports) if override.ports is not None else app_ports
            if not effective:
                continue
            block = services.setdefault(svc_name, {})
            block["ports"] = effective


def _inject_service_environment(resolved: ResolvedSpace, services: dict, declared: set[str]) -> None:
    """Add ``services.<svc>.environment`` for every compose service managed by an app.

    Per-service ``vars`` (from ``apps.<name>.services.<svc>.vars``) merge on
    top of the app's ``container_vars`` (per-service keys win on conflict).
    """
    for app_name in resolved.space.apps:
        base_env = resolved.apps[app_name].container_vars
        for svc_name, override in _managed_services(resolved, app_name).items():
            if svc_name not in declared:
                continue
            merged_env = {**base_env, **override.vars}
            if not merged_env:
                continue
            block = services.setdefault(svc_name, {})
            block.setdefault("environment", {}).update(merged_env)


def _inject_mount_volumes(resolved: ResolvedSpace, services: dict, declared: set[str]) -> None:
    """Add ``services.<svc>.volumes`` entries for every active mount/host pair.

    A mount listed in ``hosted_in: [app_name]`` lands on every compose service
    managed by that app.
    """
    from cupli.services.mounts_service import active_mounts

    active = active_mounts(resolved)
    for mount_name, mount in resolved.space.mounts.items():
        if mount_name not in active:
            continue
        host_path = str(resolved.mounts[mount_name].path)
        exec_path = resolved.mounts[mount_name].vars["MOUNT_EXEC_PATH"]
        mode = mount.mode.value
        volume_entry = f"{host_path}:{exec_path}:{mode}"
        for host_app in mount.hosted_in:
            for svc_name in _managed_services(resolved, host_app):
                if svc_name not in declared:
                    continue
                block = services.setdefault(svc_name, {})
                block.setdefault("volumes", []).append(volume_entry)


def _inject_export_binds(resolved: ResolvedSpace, services: dict, declared: set[str]) -> None:
    """Replace the named volume at a ``bind-seeded`` export's ``exec_path`` with a host bind.

    Compose merges service ``volumes`` by container target, so a long-form bind
    entry at the same target as the original named volume overrides it — the
    container then writes straight to the host ``path`` (always live for IDEs).
    Only ``bind-seeded`` exports inject here; ``sync`` exports keep the volume.
    """
    from cupli.domain.enums import ExportStrategy

    for name, export in resolved.space.exports.items():
        if export.strategy is not ExportStrategy.BIND_SEEDED:
            continue
        entry = {
            "type": "bind",
            "source": str(resolved.exports[name].path),
            "target": resolved.exports[name].vars["EXPORT_EXEC_PATH"],
        }
        for svc_name in _managed_services(resolved, export.from_app):
            if svc_name not in declared:
                continue
            block = services.setdefault(svc_name, {})
            block.setdefault("volumes", []).append(entry)


def _inject_cross_file_deps(resolved: ResolvedSpace, services: dict, declared: set[str]) -> None:
    """Add ``services.<svc>.depends_on`` for declared ``apps[*].deps``.

    Every service managed by the depending app gets the ``depends_on`` entry;
    the target side resolves to the depended-on app's PRIMARY service (the
    first one in its ``services:`` map, or its ``service:`` shorthand). The
    ``condition`` is taken from the :class:`DepSpec` when set, otherwise cupli
    picks ``service_completed_successfully`` for a ``mode: oneshot`` dep and
    ``service_started`` for anything else. ``restart`` and ``required`` are
    forwarded verbatim when they differ from compose's defaults.
    """
    for app_name, app in resolved.space.apps.items():
        if not app.deps:
            continue
        for svc_name in _managed_services(resolved, app_name):
            if svc_name not in declared:
                continue
            block = services.setdefault(svc_name, {})
            depends = block.setdefault("depends_on", {})
            for dep_name, dep_spec in app.deps.items():
                dep_svc = _primary_service(resolved, dep_name)
                if dep_svc not in declared:
                    continue
                depends.setdefault(dep_svc, _depends_entry(resolved, dep_name, dep_spec))


def _depends_entry(resolved: ResolvedSpace, dep_name: str, dep_spec) -> dict[str, object]:
    """Build the ``depends_on.<dep>`` entry from a :class:`DepSpec`."""
    condition = dep_spec.condition
    if condition is None:
        dep_mode = resolved.space.apps[dep_name].mode
        condition = "service_completed_successfully" if dep_mode is ServiceMode.ONESHOT else "service_started"
    else:
        condition = condition.value
    entry: dict[str, object] = {"condition": condition}
    if dep_spec.restart:
        entry["restart"] = True
    if not dep_spec.required:
        entry["required"] = False
    return entry


def _inject_default_networks(declared: set[str], services: dict) -> None:
    """Attach every declared service to the workspace's ``default`` network.

    Compose-merge unions ``networks`` lists, so this is a no-op when the user
    has already wired ``default`` in but explicit when they wired some other
    network and would otherwise lose default-attach.
    """
    for svc_name in declared:
        block = services.setdefault(svc_name, {})
        nets = block.setdefault("networks", [])
        if isinstance(nets, list) and "default" not in nets:
            nets.append("default")


def _primary_service(resolved: ResolvedSpace, app_name: str) -> str:
    """Return the primary compose service for an app.

    Resolution order: first key of ``services:`` map → ``service:`` shorthand
    (string form) → app name itself (also when ``service`` is an inline dict).
    """
    app = resolved.space.apps[app_name]
    if app.services:
        return next(iter(app.services))
    if isinstance(app.service, str):
        return app.service
    return app_name


def _managed_services(resolved: ResolvedSpace, app_name: str):
    """Return the ``{service_name: ServiceOverride}`` map managed by an app.

    Resolution:

    - ``services:`` map → returned verbatim.
    - ``service:`` inline ``ServiceOverride`` → one entry keyed by app's name.
    - ``service:`` string → one entry keyed by that string, no override.
    - Nothing declared → one entry keyed by app's name, no override.
    """
    from cupli.domain.models import ServiceOverride

    app = resolved.space.apps[app_name]
    if app.services:
        return dict(app.services)
    if isinstance(app.service, ServiceOverride):
        return {app_name: app.service}
    return {_primary_service(resolved, app_name): ServiceOverride()}


# --- plan ------------------------------------------------------------------


def make_plan(
    resolved: ResolvedSpace,
    *,
    services: Sequence[str] = (),
    tags: Sequence[str] = (),
    mode: DepMode | None = None,
    include_disabled: bool = False,
) -> CompiledPlan:
    """Compile a :class:`CompiledPlan` from the resolved space and a filter."""
    seeds, svc_filter_by_app = _split_seed_names(resolved, services)
    selected = closure(
        resolved,
        names=seeds,
        tags=tags,
        mode=mode,
        include_disabled=include_disabled,
    )
    pre_path, post_path, inline_path = render_overrides(resolved, selected)
    env_path = write_env_file(resolved)
    compose_files = _resolved_compose_files(resolved, selected, pre_path, post_path, inline_path)
    plan_services = _plan_services(resolved, selected, svc_filter_by_app)
    _validate_services_declared(resolved, plan_services, selected)
    return CompiledPlan(
        project_name=resolved.space.name,
        project_dir=resolved.space_dir,
        env_file=env_path,
        compose_files=tuple(compose_files),
        services=plan_services,
    )


def _split_seed_names(
    resolved: ResolvedSpace,
    names: Sequence[str],
) -> tuple[list[str], dict[str, set[str]]]:
    """Translate user-supplied names into closure seeds + per-app service filters.

    A name may be either an app name or a compose service name. App names are
    forwarded to :func:`closure` as-is. A service name is mapped to its owning
    app (by walking :func:`_managed_services`) and recorded in the per-app
    filter so :func:`_plan_services` later emits only those services.

    When the same app appears both as a bare app name and via one of its
    services, the app-form wins: the filter for that app is dropped, so all
    its managed services are emitted.
    """
    app_names = set(resolved.space.apps)
    seeds: list[str] = []
    full_apps: set[str] = set()
    svc_filter: dict[str, set[str]] = {}
    for name in names:
        if name in app_names:
            seeds.append(name)
            full_apps.add(name)
            continue
        owner = _find_owning_app(resolved, name)
        if owner is None:
            seeds.append(name)
            continue
        seeds.append(owner)
        svc_filter.setdefault(owner, set()).add(name)
    for app in full_apps:
        svc_filter.pop(app, None)
    return seeds, svc_filter


def _find_owning_app(resolved: ResolvedSpace, service_name: str) -> str | None:
    """Return the app whose managed services include ``service_name``, or None."""
    for app_name in resolved.space.apps:
        if service_name in _managed_services(resolved, app_name):
            return app_name
    return None


def _plan_services(
    resolved: ResolvedSpace,
    selected: list[str],
    svc_filter_by_app: dict[str, set[str]] | None = None,
) -> tuple[str, ...]:
    """Return every compose service managed by ``selected`` apps, in order, deduped.

    For each app in ``selected`` (already dependency-ordered by ``closure``),
    walk its ``_managed_services`` and emit every entry. A compound app
    declared via ``services:`` map contributes all its services, not just the
    primary — so ``cupli up`` starts every container the app owns.

    When ``svc_filter_by_app`` is supplied for an app, only the listed
    services from that app are emitted (used when the user targets a specific
    service of a compound app, e.g. ``cupli up fleet-2``).
    """
    seen: set[str] = set()
    out: list[str] = []
    svc_filter_by_app = svc_filter_by_app or {}
    for app_name in selected:
        filt = svc_filter_by_app.get(app_name)
        for svc_name in _managed_services(resolved, app_name):
            if filt is not None and svc_name not in filt:
                continue
            if svc_name in seen:
                continue
            seen.add(svc_name)
            out.append(svc_name)
    return tuple(out)


def target_services(resolved: ResolvedSpace, names: Sequence[str]) -> tuple[str, ...]:
    """Resolve user-named app/service seeds to compose service names without walking deps.

    Per-service lifecycle verbs (``restart``, ``stop``, ``down``, ``build``,
    ``pull``, ``ps``) act exactly on what the user named; pulling in transitive
    dependencies via ``closure`` would surprise the user — ``cupli restart api``
    would restart every database the app depends on too. ``cupli up`` keeps the
    closure-expanded plan because deps must be started first.

    Args:
        resolved: a :class:`ResolvedSpace` produced by :func:`load_space`.
        names: app or compose-service names supplied by the user. App names
            expand to every compose service the app manages (compound apps).
            Service names appear verbatim. Empty input returns an empty tuple.

    Returns:
        Stable, deduplicated compose service names in user-supplied order.
    """
    if not names:
        return ()
    seeds, svc_filter = _split_seed_names(resolved, names)
    return _plan_services(resolved, seeds, svc_filter)


def _validate_services_declared(
    resolved: ResolvedSpace,
    plan_services: tuple[str, ...],
    scope: Sequence[str],
) -> None:
    """Fail fast when a planned service is not declared in any compose source.

    A managed service must either exist in a compose-fragment parsed by
    :func:`_collect_declared_services` or be created inline via
    :func:`_build_override_inline`. Otherwise ``docker compose up`` would
    abort with ``no such service`` — surface a precise CupliError instead so
    the user sees which app/service is misconfigured.
    """
    declared = _collect_declared_services(resolved, scope)
    inline_doc = _build_override_inline(resolved, scope)
    declared |= set((inline_doc.get("services") or {}).keys())
    service_to_app: dict[str, str] = {}
    for app_name in scope:
        for svc_name in _managed_services(resolved, app_name):
            service_to_app.setdefault(svc_name, app_name)
    missing = [svc for svc in plan_services if svc not in declared]
    if not missing:
        return
    first = missing[0]
    raise CupliError(
        "E031",
        service=first,
        app=service_to_app.get(first, "?"),
        missing=", ".join(missing),
    )


def _resolved_compose_files(
    resolved: ResolvedSpace,
    selected: list[str],
    pre: Path,
    post: Path,
    inline: Path | None,
) -> list[Path]:
    """Build the ``-f`` file list for the given service selection.

    Order: ``pre`` → base composes → app composes → ``inline`` (if any) →
    ``post``. Inline file goes after user composes so per-service inline
    spec can refine an external compose-fragment of the same name; cupli's
    own ``post`` injections still win because they come last.

    ``apps[*].composes`` / ``bases[*].composes`` entries may contain
    ``${VAR}`` references (``${APP_PATH}``, ``${SPACE_PATH}``, …). Those are
    expanded against the matching component's resolved scope here, so the
    resulting list is plain absolute paths that ``COMPOSE_FILE`` can take
    verbatim.
    """
    files: list[Path] = [pre]
    base_chain = _ordered_base_chain(resolved, selected)
    for base_name in base_chain:
        files.extend(_expand_paths(resolved.space.bases[base_name].composes, resolved.bases[base_name].vars))
    for app_name in selected:
        files.extend(_expand_paths(resolved.space.apps[app_name].composes, resolved.apps[app_name].vars))
    if inline is not None:
        files.append(inline)
    files.append(post)
    return files


def _ordered_base_chain(resolved: ResolvedSpace, selected: list[str]) -> list[str]:
    """Distinct bases referenced by ``selected``, in first-seen order."""
    seen: set[str] = set()
    chain: list[str] = []
    for app_name in selected:
        for base_name in resolved.space.apps[app_name].bases:
            if base_name in seen:
                continue
            seen.add(base_name)
            chain.append(base_name)
    return chain


def _expand_paths(raw_paths: list[str], scope: dict[str, str]) -> list[Path]:
    """Substitute ``${VAR}`` references in ``raw_paths`` and absolutise them."""
    from pathlib import Path as _Path

    from cupli.core.env_resolver import substitute

    out: list[Path] = []
    for raw in raw_paths:
        expanded = substitute(raw, scope)
        candidate = _Path(expanded)
        out.append(candidate if candidate.is_absolute() else candidate.resolve())
    return out


# --- invoke ----------------------------------------------------------------


def build_argv(plan: CompiledPlan, command_args: Sequence[str]) -> list[str]:
    """Build the docker compose argv list.

    Everything that docker compose accepts via ``COMPOSE_*`` env vars is
    pushed there (see :func:`build_env`). The argv stays minimal —
    ``["docker", "compose", "--env-file", <file>, *command_args]``. The
    ``--env-file`` flag is kept because ``COMPOSE_ENV_FILES`` only landed in
    compose 2.24 and we do not pin that floor yet.
    """
    argv = ["docker", "compose"]
    if plan.env_file is not None:
        argv.extend(["--env-file", str(plan.env_file)])
    argv.extend(command_args)
    return argv


def build_env(plan: CompiledPlan) -> dict[str, str]:
    """Build the ``COMPOSE_*`` env dict forwarded to docker compose.

    Sets:

    - ``COMPOSE_PROJECT_NAME`` — replaces ``--project-name`` on the argv.
    - ``COMPOSE_PROJECT_DIRECTORY`` — replaces ``--project-directory``.
    - ``COMPOSE_FILE`` — separator-joined list of every ``-f`` file.
    - ``COMPOSE_PATH_SEPARATOR`` — explicit, so the value stays valid when
      a child process resets cwd or changes platform conventions.
    """
    return {
        "COMPOSE_PROJECT_NAME": plan.project_name,
        "COMPOSE_PROJECT_DIRECTORY": str(plan.project_dir),
        "COMPOSE_FILE": COMPOSE_PATH_SEP.join(str(path) for path in plan.compose_files),
        "COMPOSE_PATH_SEPARATOR": COMPOSE_PATH_SEP,
    }


def resolved_compose_config(plan: CompiledPlan) -> dict | None:
    """Return the merged compose config (``docker compose config --format json``).

    Returns ``None`` when docker is unreachable, the command fails, or the
    output is empty. Callers that walk binds / volumes (mount-target prep,
    host bridges, export materialisation) share this single read.
    """
    import json as _json

    argv = build_argv(plan, ["config", "--format", "json"])
    env = {**os.environ, **build_env(plan)}
    completed = run_command(argv, cwd=plan.project_dir, env=env, stream=False, check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        config = _json.loads(completed.stdout)
    except ValueError:
        return None
    return config if isinstance(config, dict) else None


def shared_volume_inits(config: dict | None) -> list[tuple[str, str, str]]:
    """Return ``(real_volume, mountpoint, image)`` for named volumes shared by ≥2 services.

    A fresh named volume is initialised from image content on first mount; when
    several services of an app mount the SAME fresh volume, ``docker compose up``
    races their concurrent inits (``failed to mkdir …/_data/…: file exists``).
    Pre-initialising each such volume once, serially, side-steps the race.
    """
    if config is None:
        return []
    services = config.get("services") or {}
    top = config.get("volumes") or {}
    by_volume: dict[str, dict[str, tuple[str, str]]] = {}
    for svc_name, svc in services.items():
        if not isinstance(svc, dict) or not svc.get("image"):
            continue
        for vol in svc.get("volumes") or []:
            if not (isinstance(vol, dict) and vol.get("type") == "volume" and vol.get("source") and vol.get("target")):
                continue
            real = str((top.get(str(vol["source"])) or {}).get("name", vol["source"]))
            by_volume.setdefault(real, {})[svc_name] = (str(vol["target"]), str(svc["image"]))
    out: list[tuple[str, str, str]] = []
    for real, per_service in by_volume.items():
        if len(per_service) >= 2:
            target, image = next(iter(per_service.values()))
            out.append((real, target, image))
    return out


def prepare_shared_volumes(config: dict | None) -> None:
    """Initialise each not-yet-created shared named volume once (serially).

    No-op for volumes that already exist (the race only bites fresh volumes) and
    best-effort throughout — never blocks ``up`` on a prep failure.
    """
    for real, target, image in shared_volume_inits(config):
        inspect = run_command(["docker", "volume", "inspect", real], stream=False, check=False)
        if inspect.returncode == 0:
            continue  # already initialised — concurrent mounts won't race
        run_command(["docker", "run", "--rm", "-v", f"{real}:{target}", image, "true"], stream=False, check=False)


def ensure_images(plan: CompiledPlan, service_images: dict[str, str]) -> None:
    """Build any service whose image is not present locally (``docker compose build``).

    Used before bind-seed copy and shared-volume init so those steps read content
    from a real image on a fresh deploy (where the image is not built yet).
    """
    missing = [
        svc
        for svc, image in service_images.items()
        if run_command(["docker", "image", "inspect", image], stream=False, check=False).returncode != 0
    ]
    if missing:
        invoke(plan, ["build", *sorted(missing)])


_MOUNT_PREP_VERBS: frozenset[str] = frozenset({"up", "build", "run", "watch"})
"""Compose verbs that materialise mounts and benefit from pre-created targets."""


def invoke(
    plan: CompiledPlan,
    command_args: Sequence[str],
    *,
    stream: bool = True,
    check: bool = True,
) -> CompletedProcess[str]:
    """Render-then-run docker compose for ``plan``.

    Compose receives its file list and project name via ``COMPOSE_*`` env
    vars (see :func:`build_env`) rather than long ``-f`` / ``--project-name``
    flags. Keeps the argv readable in debug logs and lets users invoke
    ``docker compose ...`` directly with the same env (via ``cupli wrap``).

    Verbs that materialise mounts (``up`` / ``build`` / ``run`` / ``watch``)
    are preceded by :func:`prepare_mount_targets` so host placeholders for
    sub-mounts under bind targets are created as the cupli user, not as
    root by the docker daemon.
    """
    if command_args and command_args[0] in _MOUNT_PREP_VERBS:
        from cupli.services.mount_targets import prepare_mount_targets

        prepare_mount_targets(plan)
    argv = build_argv(plan, command_args)
    env = build_env(plan)
    return run_command(argv, cwd=plan.project_dir, env=env, stream=stream, check=check)


__all__ = (
    "COMPOSE_PATH_SEP",
    "CompiledPlan",
    "build_argv",
    "build_env",
    "ensure_images",
    "invoke",
    "make_plan",
    "prepare_shared_volumes",
    "render_overrides",
    "resolved_compose_config",
    "shared_volume_inits",
    "target_services",
    "write_env_file",
)
