"""Pydantic v2 schema models for ``space.cupli.yaml``.

Models are ``frozen`` (immutable) and ``extra="forbid"`` (typos surface as
errors). Cross-references between sections (``apps[*].bases``,
``apps[*].deps``, ``mounts[*].hosted_in``) are validated by a single
``model_validator`` on ``SpaceModel`` so error messages can list known names.

Resolution of defaults that depend on the host filesystem (e.g.
``app.path = ${APPS_PATH}/<name>``) is NOT done here — that is the loader's
job in the next milestone. The schema only validates structural correctness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Self

if TYPE_CHECKING:
    from collections.abc import Iterable

from cupli.domain.consts import (
    DEFAULT_MAX_VERSION,
    DEFAULT_MIN_VERSION,
    DEFAULT_SCHEMA_VERSION,
    NAME_PATTERN,
    TAG_PATTERN,
    VERSION_PATTERN,
)
from cupli.domain.enums import DepMode, MacVolumeMode, MountMode, ServiceMode


def _coerce_scalar_to_str(value: object) -> object:
    """Coerce YAML scalar values (int/float/bool/None/datetime) to str.

    Pydantic's default coercion accepts strings only; YAML 1.2 produces typed
    scalars. The cupli convention is "all variables are strings" — match it.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return str(value)


def _wrap_str_as_list(value: object) -> object:
    """Accept either ``"x"`` or ``["x", "y"]`` and yield a list."""
    if isinstance(value, str):
        return [value]
    return value


def _deps_to_dict(value: object) -> object:
    """Accept either a list of names or a dict of name → mode-list.

    Lists ``[a, b]`` are normalised to ``{a: [default], b: [default]}``.
    """
    if isinstance(value, list):
        return {item: [DepMode.DEFAULT.value] for item in value}
    return value


def _none_as_empty_dict(value: object) -> object:
    """Treat YAML ``vars:`` (parsed as ``None``) as an empty dict."""
    if value is None:
        return {}
    return value


def _services_list_to_dict(value: object) -> object:
    """Accept ``services:`` as either a map or a list of service names.

    A list ``[foo, bar]`` is normalised to ``{foo: {}, bar: {}}`` so users
    can declare compound apps without writing empty trailing braces.
    """
    if isinstance(value, list):
        return {item: {} for item in value}
    return value


# --- atomic field types ----------------------------------------------------

NameStr = Annotated[
    str,
    StringConstraints(pattern=NAME_PATTERN.pattern, min_length=1, max_length=64),
]
"""Identifier for spaces, apps, bases, mounts, commands, services."""

TagStr = Annotated[
    str,
    StringConstraints(pattern=TAG_PATTERN.pattern, min_length=1, max_length=32),
]
"""Lower-case tag identifier."""

VersionStr = Annotated[
    str,
    StringConstraints(pattern=VERSION_PATTERN.pattern, min_length=1, max_length=16),
]
"""Semver-ish string with optional ``*`` wildcard."""

ScalarStr = Annotated[str, BeforeValidator(_coerce_scalar_to_str)]
"""String field that accepts any YAML scalar and coerces to ``str``."""

StrList = Annotated[list[str], BeforeValidator(_wrap_str_as_list)]
"""List of strings; bare string is wrapped into a one-element list."""

NameList = Annotated[list[NameStr], BeforeValidator(_wrap_str_as_list)]
"""List of identifiers; bare string is wrapped into a one-element list."""

TagList = Annotated[list[TagStr], BeforeValidator(_wrap_str_as_list)]
"""List of tag identifiers; bare string is wrapped into a one-element list."""

DepMap = Annotated[
    dict[NameStr, list[DepMode]],
    BeforeValidator(_deps_to_dict),
]
"""Mapping from dependency name to its mode tags."""

ScalarMap = Annotated[dict[str, ScalarStr], BeforeValidator(_none_as_empty_dict)]
"""String-to-scalar map; ``key:`` with no value (YAML null) is treated as an empty dict."""


# --- nested objects --------------------------------------------------------


class _Frozen(BaseModel):
    """Base model with the cupli-wide config (frozen, no extra)."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class HooksOverride(_Frozen):
    """Per-target hook overrides used by ``cupli set-hooks``.

    Attributes:
        service: docker-compose service to exec into (default: target's service).
        working_dir: working directory inside the container.
        enabled: whether to install shims for this target.
    """

    service: str | None = None
    working_dir: str | None = None
    enabled: bool = True


class ServiceOverride(BaseModel):
    """Per-compose-service tweak inside an ``apps.<name>.services:`` map.

    Cupli-specific fields are ``vars`` and ``ports`` — everything else is
    treated as a docker-compose service spec and flushed verbatim to a
    generated ``docker-compose.inline.yml`` (it can extend an existing compose
    service or create a brand-new one).

    Semantics:

    - ``vars`` merge on top of the parent app's ``vars`` (per-service wins).
    - ``ports`` REPLACES the parent app's list when present (``[]`` opts out).
    - Anything else (``image``, ``build``, ``command``, ``environment``,
      ``volumes``, ``depends_on``, …) is plain compose syntax. ``${VAR}``
      references are left untouched here and resolved by docker compose
      against ``override.env``.
    """

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    vars: ScalarMap = Field(default_factory=dict)
    ports: StrList | None = None

    @property
    def compose_spec(self) -> dict[str, Any]:
        """Return the dict of arbitrary compose-syntax fields (everything except cupli-specific ones).

        Uses ``model_dump(mode="json")`` so the result contains only plain
        Python types — safe for ``yaml.safe_dump`` later in the pipeline.
        """
        dumped = self.model_dump(mode="json")
        for cupli_key in ("vars", "ports"):
            dumped.pop(cupli_key, None)
        return dumped


class CommandShortcut(_Frozen):
    """One ``commands[<name>]`` entry.

    By default reachable only via ``cupli sc <name>``. Set
    ``top_level: true`` to ALSO register it as a first-class ``cupli <name>``
    verb (collisions with builtin commands are ignored).

    Attributes:
        container: app name whose service runs the command.
        run: shell command line executed inside the container.
        workdir: working directory inside the container.
        help: short help string shown in ``cupli --help``.
        top_level: when True, the command is promoted to a top-level verb
            so ``cupli <name>`` works alongside ``cupli sc <name>``.
    """

    container: NameStr
    run: str
    workdir: str | None = None
    help: str | None = None
    top_level: bool = False


class _Component(_Frozen):
    """Fields shared between apps, bases, and mounts."""

    path: str | None = None
    repo: str | None = None
    branch: str | None = None
    post_clone: str | None = None
    vars: ScalarMap = Field(default_factory=dict)
    envs: StrList = Field(default_factory=list)
    init_vars: ScalarMap = Field(default_factory=dict)


class BaseAppModel(_Component):
    """One ``bases[<name>]`` entry.

    Bases are inheritable templates included by apps. Their ``composes`` files
    are prepended to including-apps' compose list.

    Attributes:
        composes: compose files to merge into including apps.
    """

    composes: StrList = Field(default_factory=list)


class AppModel(_Component):
    """One ``apps[<name>]`` entry.

    Attributes:
        bases: base names to inherit from (multi-inheritance, C3 ordered).
        deps: cupli-level start dependencies, mode-tagged.
        tags: free-form tags used by ``cupli start --tag``.
        mode: how the service runs (``up``, ``oneshot``, ``disabled``).
        composes: compose files defining this app's services.
        service: docker-compose service binding for this app.
            * Omit it: app drives the compose service whose name == app's name.
            * String: name of the existing compose service to bind to.
            * Mapping: inline single-service spec — any docker-compose fields,
              service name defaults to the app's name. Removes the need for a
              separate compose file when one service is enough.
            Mutually exclusive with the ``services:`` map.
        services: multi-service map for compound apps (celery + workers + beat).
            Each entry can mix cupli-specific keys (``vars``, ``ports``) with
            arbitrary docker-compose attributes.
        ports: compose-style port mappings (``"8000:8000"``, ``"127.0.0.1:8000:8000"``,
            ``"5432:5432/tcp"``) injected into the service's ``ports:`` block. ``${VAR}``
            references are substituted in the app's scope.
        forward_ssh: opt-in to forward ``SSH_AUTH_SOCK`` into the container.
    """

    bases: NameList = Field(default_factory=list)
    deps: DepMap = Field(default_factory=dict)
    tags: TagList = Field(default_factory=list)
    mode: ServiceMode = ServiceMode.UP
    composes: StrList = Field(default_factory=list)
    service: str | ServiceOverride | None = None
    services: Annotated[
        dict[NameStr, ServiceOverride] | None,
        BeforeValidator(_services_list_to_dict),
    ] = None
    """Multi-service map. When set, app's vars/ports apply to every listed
    service; each entry can override ``vars`` (merged) and ``ports`` (replaced)
    per service. Mutually exclusive with ``service:`` (shorthand for one).

    Accepts either form:

    .. code-block:: yaml

        services:
          - api
          - worker
          - beat

        # equivalent to:
        services:
          api: {}
          worker: {}
          beat: {}
    """
    ports: StrList = Field(default_factory=list)
    forward_ssh: bool = False

    @model_validator(mode="after")
    def _validate_service_vs_services(self) -> Self:
        """``service:`` (single) and ``services:`` (map) are mutually exclusive."""
        if self.service is not None and self.services is not None:
            raise ValueError(
                "an app declares either `service:` (one compose service) or `services:` (map of services) — not both",
            )
        return self

    def primary_service_name(self, app_name: str) -> str:
        """Return the compose service name this app binds to.

        Resolution: first key of ``services:`` map → ``service:`` (string
        shorthand) → ``app_name`` itself (also when ``service:`` is an inline
        ``ServiceOverride``).
        """
        if self.services:
            return next(iter(self.services))
        if isinstance(self.service, str):
            return self.service
        return app_name


class MountModel(_Component):
    """One ``mounts[<name>]`` entry.

    Attributes:
        hosted_in: app names whose containers receive the mount.
        exec_path: absolute POSIX path inside the container.
        mode: read-write or read-only bind-mount.
        mac_volume: optional macOS volume consistency hint.
    """

    hosted_in: NameList = Field(min_length=1)
    exec_path: str
    mode: MountMode = MountMode.RW
    mac_volume: MacVolumeMode | None = None

    @model_validator(mode="after")
    def _validate_exec_path(self) -> Self:
        """``exec_path`` must be absolute (or start with a ``${VAR}`` ref)."""
        value = self.exec_path
        if value.startswith("${"):
            return self
        if not value.startswith("/"):
            raise ValueError(
                f"exec_path must be an absolute POSIX path (start with '/'), got: {value!r}",
            )
        return self


# --- top-level space -------------------------------------------------------


class SpaceModel(_Frozen):
    """Top-level cupli space.

    Attributes:
        schema_version: schema version pin; ``1`` is the only supported value.
        name: identifier used as docker network and compose project prefix.
        cupli_min: minimum cupli version required (semver or ``*``).
        cupli_max: maximum cupli version required (semver or ``*``).
        extends: optional path to a parent space.cupli.yaml (one level only).
        envs: env files loaded before ``vars`` are resolved.
        vars: space-scope variables (later vars may reference earlier ones).
        bases: declared base templates.
        apps: declared apps (non-empty).
        mounts: declared library mounts.
        hooks: optional per-target hook overrides for ``cupli set-hooks``.
        commands: workspace-defined CLI shortcuts.
        networks: optional docker-compose ``networks:`` block. Map of network
            name to compose-spec (any compose ``networks.<name>.*`` field is
            accepted verbatim). Merged into ``docker-compose.pre.yml`` so the
            user can declare custom networks (e.g. with a fixed name or
            driver) alongside cupli's auto ``default`` attach.
    """

    schema_version: Literal[1] = DEFAULT_SCHEMA_VERSION
    name: NameStr
    cupli_min: VersionStr = DEFAULT_MIN_VERSION
    cupli_max: VersionStr = DEFAULT_MAX_VERSION
    extends: str | None = None
    envs: StrList = Field(default_factory=list)
    vars: ScalarMap = Field(default_factory=dict)
    bases: dict[NameStr, BaseAppModel] = Field(default_factory=dict)
    apps: dict[NameStr, AppModel] = Field(min_length=1)
    mounts: dict[NameStr, MountModel] = Field(default_factory=dict)
    hooks: dict[NameStr, HooksOverride] = Field(default_factory=dict)
    commands: dict[NameStr, CommandShortcut] = Field(default_factory=dict)
    networks: dict[NameStr, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_cross_refs(self) -> Self:
        """Validate inter-section references (apps.bases, apps.deps, mounts.hosted_in)."""
        _check_app_bases(self.apps, self.bases)
        _check_app_deps(self.apps)
        _check_mount_hosts(self.mounts, self.apps)
        _check_command_containers(self.commands, self.apps)
        return self


# --- cross-reference helpers (kept at module scope to honour low-complexity rule) -


def _check_app_bases(apps: dict[str, AppModel], bases: dict[str, BaseAppModel]) -> None:
    """Raise when an app references an undeclared base."""
    known = set(bases)
    for app_name, app in apps.items():
        unknown = [b for b in app.bases if b not in known]
        if not unknown:
            continue
        raise ValueError(
            f"apps.{app_name}.bases references unknown base(s): {unknown!r}. Declared bases: {sorted(known)!r}",
        )


def _check_app_deps(apps: dict[str, AppModel]) -> None:
    """Raise when an app references an undeclared dep."""
    known = set(apps)
    for app_name, app in apps.items():
        unknown = [d for d in app.deps if d not in known]
        if not unknown:
            continue
        raise ValueError(
            f"apps.{app_name}.deps references unknown app(s): {unknown!r}. Declared apps: {sorted(known)!r}",
        )


def _check_mount_hosts(mounts: dict[str, MountModel], apps: dict[str, AppModel]) -> None:
    """Raise when a mount references an undeclared host app."""
    known = set(apps)
    for mount_name, mount in mounts.items():
        unknown = [h for h in mount.hosted_in if h not in known]
        if not unknown:
            continue
        raise ValueError(
            f"mounts.{mount_name}.hosted_in references unknown app(s): {unknown!r}. Declared apps: {sorted(known)!r}",
        )


def _check_command_containers(
    commands: dict[str, CommandShortcut],
    apps: dict[str, AppModel],
) -> None:
    """Raise when a workspace command refers to an undeclared container app."""
    known = set(apps)
    for cmd_name, cmd in commands.items():
        if cmd.container in known:
            continue
        raise ValueError(
            f"commands.{cmd_name}.container '{cmd.container}' is not a declared app. Declared apps: {sorted(known)!r}",
        )


def iter_all_components(
    space: SpaceModel,
) -> Iterable[tuple[str, _Component]]:
    """Yield (name, component) pairs across apps, bases, and mounts.

    Useful for ``space sync`` and ``set-hooks`` discovery.
    """
    for name, comp in space.bases.items():
        yield name, comp
    for name, app in space.apps.items():
        yield name, app
    for name, mount in space.mounts.items():
        yield name, mount


__all__ = (
    "AppModel",
    "BaseAppModel",
    "CommandShortcut",
    "HooksOverride",
    "MountModel",
    "NameList",
    "NameStr",
    "ScalarStr",
    "SpaceModel",
    "StrList",
    "TagStr",
    "VersionStr",
    "iter_all_components",
)
