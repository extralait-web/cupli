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

import re
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
from cupli.domain.enums import (
    DepCondition,
    DepMode,
    ExecuteMode,
    ExportStrategy,
    MacVolumeMode,
    MountMode,
    RefreshHook,
    ServiceMode,
)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z][\w-]*)\s*\}\}")
"""Matches ``{{name}}`` argument placeholders inside a command's ``run`` line."""


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


def _deps_to_specs(value: object) -> object:
    """Normalise a ``deps:`` declaration into ``{name: dep-spec dict}``.

    Accepted input forms (back-compat preserved):

    - list of names ``[postgres, redis]`` → ``{postgres: {}, redis: {}}``
      (each name uses the default DepSpec — default mode, auto condition).
    - dict whose value is:

      - ``None`` (YAML ``~``) → ``{}`` (defaults).
      - a string (a :class:`DepCondition` value) → ``{condition: <value>}``.
      - a list of strings → ``{modes: <list>}`` (back-compat with mode tags).
      - a dict → passed through verbatim (full ``DepSpec`` spec).

    The mode tag (cupli-side ``default``/``hook``/``full``) and the compose
    condition (``service_started``/``service_healthy``/``service_completed_successfully``)
    occupy disjoint name spaces, so a bare string is unambiguous.
    """
    if isinstance(value, list):
        return {item: {} for item in value}
    if not isinstance(value, dict):
        return value
    result: dict[str, object] = {}
    for name, raw in value.items():
        if raw is None:
            result[name] = {}
            continue
        if isinstance(raw, str):
            result[name] = {"condition": raw}
            continue
        if isinstance(raw, list):
            result[name] = {"modes": raw}
            continue
        result[name] = raw
    return result


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


def _join_run_lines(value: object) -> object:
    """Accept a command ``run`` as a string or a list of lines.

    A list is joined with newlines so multi-line scripts can be declared either
    as a YAML block scalar or as an explicit list of commands.
    """
    if isinstance(value, list):
        return "\n".join(str(line) for line in value)
    return value


def _args_shorthand_to_dicts(value: object) -> object:
    """Accept ``args`` as bare names or full arg-spec mappings.

    A bare string entry ``path`` expands to a required positional string
    argument ``{name: path, required: true}``; mappings pass through untouched.
    """
    if not isinstance(value, list):
        return value
    expanded: list[object] = []
    for item in value:
        if isinstance(item, str):
            expanded.append({"name": item, "required": True})
            continue
        expanded.append(item)
    return expanded


def _coerce_null_block_values(value: object) -> object:
    """Coerce ``{name: None}`` entries to ``{name: {}}`` in a top-level block.

    A YAML entry with no body (``data:`` under ``volumes:``) parses its inner
    value as ``None``; docker compose reads a null body as a default-driver
    entry. Normalise it to an empty dict so the typed schema accepts the common
    named-volume idiom.
    """
    if not isinstance(value, dict):
        return value
    return {key: ({} if inner is None else inner) for key, inner in value.items()}


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


class DepSpec(BaseModel):
    """One ``apps[*].deps[<name>]`` entry.

    Captures both cupli's per-dep ``modes`` tags (used for ``cupli up --mode``
    filtering) and the docker-compose ``depends_on`` semantics: ``condition``,
    ``restart``, and ``required``. The list/string/null short forms in YAML
    are normalised into this spec by :func:`_deps_to_specs` before validation.

    Attributes:
        modes: cupli-side mode tags. A dep is walked by ``--mode <m>`` only
            when ``m`` is in this list.
        condition: compose start condition. ``None`` (default) → cupli picks
            ``service_completed_successfully`` for a ``mode: oneshot`` dep and
            ``service_started`` otherwise.
        restart: when True, compose restarts the depending service if the
            dependency restarts (compose ``depends_on.<svc>.restart``).
        required: when False, the dep is "soft" — compose still starts the
            depending service if the dep cannot start (compose
            ``depends_on.<svc>.required: false``). Default True.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    modes: list[DepMode] = Field(default_factory=lambda: [DepMode.DEFAULT])
    condition: DepCondition | None = None
    restart: bool = False
    required: bool = True


DepMap = Annotated[
    dict[NameStr, DepSpec],
    BeforeValidator(_deps_to_specs),
]
"""Mapping from dependency name to a :class:`DepSpec`. Short YAML forms are
coerced — see :func:`_deps_to_specs`."""

ScalarMap = Annotated[dict[str, ScalarStr], BeforeValidator(_none_as_empty_dict)]
"""String-to-scalar map; ``key:`` with no value (YAML null) is treated as an empty dict."""

ComposeBlockMap = Annotated[
    dict[NameStr, dict[str, Any]],
    BeforeValidator(_coerce_null_block_values),
]
"""Top-level compose block (``networks``/``volumes``/``secrets``/``configs``).

Values are compose-spec verbatim. A null inner body (``data:`` with no
mapping) is coerced to an empty dict so default-driver entries parse cleanly.
"""


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


class CommandArg(_Frozen):
    """One declared parameter of a ``commands[<name>]`` shortcut.

    Attributes:
        name: identifier; used both as the ``{{name}}`` placeholder inside the
            command's ``run`` line and as the CLI argument/option name.
        help: short description shown in ``cupli <command> --help``.
        type: value type — ``str`` (default), ``int``, or ``bool``.
        option: when True the parameter is a ``--name`` option; otherwise a
            positional argument. A ``bool`` type is always an option (flag).
        short: optional single-letter alias for an option (``l`` renders ``-l``).
        required: whether the parameter must be supplied. Mutually exclusive
            with ``default``.
        default: value substituted when the parameter is omitted.
    """

    name: NameStr
    help: str | None = None
    type: Literal["str", "int", "bool"] = "str"
    option: bool = False
    short: str | None = None
    required: bool = False
    default: ScalarStr | None = None

    @property
    def is_option(self) -> bool:
        """Return True when the parameter renders as a ``--name`` option.

        Explicit ``option: true`` or a ``bool`` type (always a flag) both make
        the parameter an option rather than a positional argument.
        """
        return self.option or self.type == "bool"

    @property
    def is_positional(self) -> bool:
        """Return True for a positional argument."""
        return self.is_option is False

    @model_validator(mode="after")
    def _validate_arg(self) -> Self:
        """Reject contradictory or unrepresentable argument declarations."""
        if not self.name.isidentifier():
            raise ValueError(
                f"command arg name '{self.name}' must be a valid identifier "
                "(letters, digits, underscore; no '-') so it maps to a CLI parameter",
            )
        if self.required and self.default is not None:
            raise ValueError(f"command arg '{self.name}' sets both `required` and `default` — choose one")
        if self.short is not None and self.is_option is False:
            raise ValueError(f"command arg '{self.name}' sets `short` but is positional; `short` applies to options")
        return self


class CommandShortcut(_Frozen):
    """One ``commands[<name>]`` entry.

    By default reachable only via ``cupli sc <name>``. Set
    ``top_level: true`` to ALSO register it as a first-class ``cupli <name>``
    verb (collisions with builtin commands are ignored).

    Attributes:
        container: one or more app names whose service runs the command. A bare
            string is wrapped into a one-element list.
        run: shell command line executed inside the container. Accepts a single
            string (block scalars allowed) or a list of lines joined with
            newlines. ``{{name}}`` placeholders are substituted from declared
            ``args``.
        workdir: working directory inside the container.
        help: short help string shown in ``cupli --help``.
        top_level: when True, the command is promoted to a top-level verb
            so ``cupli <name>`` works alongside ``cupli sc <name>``.
        group: optional label; top-level commands are grouped under it in
            ``cupli --help`` and the ``cupli sc`` listing.
        execute: strategy when ``container`` lists several apps — sequential
            (fail-fast, default), continue, or parallel.
        args: declared parameters surfaced as typed CLI arguments/options and
            substituted into ``run`` via ``{{name}}`` placeholders. A bare list
            of names is shorthand for required positional string arguments.
        strict: when False (default), CLI tokens not matching a declared ``arg``
            are forwarded verbatim to the end of the command (flags and
            positionals alike); when True, an unknown token is rejected. Only
            relevant when ``args`` is declared.
    """

    container: NameList = Field(min_length=1)
    run: Annotated[str, BeforeValidator(_join_run_lines)]
    workdir: str | None = None
    help: str | None = None
    top_level: bool = False
    group: str | None = None
    execute: ExecuteMode = ExecuteMode.SEQUENTIAL
    args: Annotated[list[CommandArg], BeforeValidator(_args_shorthand_to_dicts)] = Field(default_factory=list)
    strict: bool = False

    @model_validator(mode="after")
    def _validate_args(self) -> Self:
        """Validate argument uniqueness, positional order, and run placeholders."""
        _check_unique_arg_names(self.args)
        _check_positional_order(self.args)
        _check_run_placeholders(self.run, self.args)
        return self


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


def _require_absolute_posix(value: str, *, field: str) -> str:
    """Return ``value`` when it is an absolute POSIX path or a ``${VAR}`` ref.

    A leading ``$`` is accepted because the path may be a variable reference
    resolved later by the loader (``${APP_PATH}/...``); otherwise it must start
    with ``/``.
    """
    if value.startswith(("$", "/")):
        return value
    raise ValueError(
        f"{field} must be an absolute POSIX path (start with '/'), got: {value!r}",
    )


class HostBridgeSpec(_Frozen):
    """Expanded form of a mount's ``host_bridge`` declaration.

    Used when the auto-derived host link (``<bind-source> + (exec_path −
    bind-target)``) is not what you want, or to opt out of relative symlinks.

    Attributes:
        link: explicit host path for the bridge symlink. Overrides the
            auto-derived link. ``${VAR}`` references are resolved in the
            mount's scope. When ``None``, cupli derives the link from the
            hosting app's workdir bind.
        relative: when True (default), create a relative symlink so the
            workspace stays portable across machines.
    """

    link: str | None = None
    relative: bool = True


class MountModel(_Component):
    """One ``mounts[<name>]`` entry.

    Attributes:
        hosted_in: app names whose containers receive the mount.
        exec_path: absolute POSIX path inside the container.
        mode: read-write or read-only bind-mount.
        mac_volume: optional macOS volume consistency hint.
        host_bridge: opt-in host symlink so host tooling (IDEs, workspace
            resolvers) sees the mount at the same relative path the container
            uses. ``true`` enables auto-derivation; a mapping is a
            :class:`HostBridgeSpec` for overrides. ``false`` (default) is off.
    """

    hosted_in: NameList = Field(min_length=1)
    exec_path: str
    mode: MountMode = MountMode.RW
    mac_volume: MacVolumeMode | None = None
    host_bridge: bool | HostBridgeSpec = False

    @model_validator(mode="after")
    def _validate_exec_path(self) -> Self:
        """``exec_path`` must be absolute (or start with a ``${VAR}`` ref)."""
        _require_absolute_posix(self.exec_path, field="exec_path")
        return self

    @property
    def bridge_enabled(self) -> bool:
        """Return True when this mount maintains a host_bridge symlink."""
        return self.host_bridge is not False

    @property
    def bridge_spec(self) -> HostBridgeSpec:
        """Return the effective :class:`HostBridgeSpec` (defaults when ``true``)."""
        if isinstance(self.host_bridge, HostBridgeSpec):
            return self.host_bridge
        return HostBridgeSpec()


class ExportModel(_Frozen):
    """One ``exports[<name>]`` entry.

    Materialises a directory built inside a container (typically living in a
    named volume — ``node_modules``, optionally ``.venv``) onto the host so
    IDEs that only resolve from the local filesystem see it.

    Export is for IDE indexing, NOT for running host tooling: the exported
    tree may carry native binaries built for the image's libc, not the host's.

    Attributes:
        from_app: the app (single) whose service owns the source directory.
        exec_path: absolute POSIX source path inside the container.
        path: host destination path (``${VAR}`` references resolved in scope).
        strategy: ``sync`` (default — keep the named volume, copy to host on
            ``refresh_on``) or ``bind-seeded`` (turn ``exec_path`` into a host
            bind seeded from the image).
        refresh_on: lifecycle events that trigger a refresh (default
            ``[build]``).
        gitignore: when True (default), add ``path`` to the root ``.gitignore``.
        mac_volume: optional macOS volume consistency hint.
        rewrite_paths: experimental — rewrite absolute container paths inside
            exported files to their host equivalents on sync (for editable
            ``.venv`` installs). Off by default; see ``E034``.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    from_app: NameStr = Field(alias="from")
    exec_path: str
    path: str
    strategy: ExportStrategy = ExportStrategy.SYNC
    refresh_on: Annotated[list[RefreshHook], BeforeValidator(_wrap_str_as_list)] = Field(
        default_factory=lambda: [RefreshHook.BUILD],
    )
    gitignore: bool = True
    mac_volume: MacVolumeMode | None = None
    rewrite_paths: bool = False

    @model_validator(mode="after")
    def _validate_exec_path(self) -> Self:
        """``exec_path`` must be absolute (or start with a ``${VAR}`` ref)."""
        _require_absolute_posix(self.exec_path, field="exec_path")
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
        volumes: optional top-level ``volumes:`` block. Named volumes are
            declared verbatim into ``docker-compose.pre.yml`` so inline
            services can reference them (e.g. ``minio_data:/data``) without a
            separate compose file. No synthetic default is injected.
        secrets: optional top-level ``secrets:`` block. Secret definitions are
            declared verbatim so service-level ``secrets:`` references (e.g.
            build secrets) resolve. No synthetic default is injected.
        configs: optional top-level ``configs:`` block. Config definitions are
            declared verbatim so service-level ``configs:`` references resolve.
            No synthetic default is injected.
        exports: optional ``exports:`` block. Each entry materialises a
            container-built directory (e.g. ``node_modules``) onto the host so
            IDEs resolve dependencies locally. Opt-in; absent by default.
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
    networks: ComposeBlockMap = Field(default_factory=dict)
    volumes: ComposeBlockMap = Field(default_factory=dict)
    secrets: ComposeBlockMap = Field(default_factory=dict)
    configs: ComposeBlockMap = Field(default_factory=dict)
    exports: dict[NameStr, ExportModel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_cross_refs(self) -> Self:
        """Validate inter-section references (apps.bases, apps.deps, mounts.hosted_in, exports.from)."""
        _check_app_bases(self.apps, self.bases)
        _check_app_deps(self.apps)
        _check_mount_hosts(self.mounts, self.apps)
        _check_command_containers(self.commands, self.apps)
        _check_export_sources(self.exports, self.apps)
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
        unknown = [name for name in cmd.container if name not in known]
        if not unknown:
            continue
        raise ValueError(
            f"commands.{cmd_name}.container references unknown app(s): {unknown!r}. Declared apps: {sorted(known)!r}",
        )


def _check_export_sources(exports: dict[str, ExportModel], apps: dict[str, AppModel]) -> None:
    """Raise when an export references an undeclared ``from`` app."""
    known = set(apps)
    for export_name, export in exports.items():
        if export.from_app in known:
            continue
        raise ValueError(
            f"exports.{export_name}.from references unknown app {export.from_app!r}. Declared apps: {sorted(known)!r}",
        )


def _check_unique_arg_names(args: list[CommandArg]) -> None:
    """Reject duplicate argument names within one command."""
    seen: set[str] = set()
    for arg in args:
        if arg.name in seen:
            raise ValueError(f"duplicate command arg name '{arg.name}'")
        seen.add(arg.name)


def _check_positional_order(args: list[CommandArg]) -> None:
    """Required positional arguments must precede optional ones (click rule)."""
    seen_optional = False
    for arg in args:
        if arg.is_option:
            continue
        if arg.required and seen_optional:
            raise ValueError(
                f"command arg '{arg.name}': required positional arguments must precede optional ones",
            )
        seen_optional = seen_optional or arg.required is False


def _check_run_placeholders(run: str, args: list[CommandArg]) -> None:
    """Every ``{{name}}`` placeholder in ``run`` must reference a declared arg."""
    if not args:
        return
    declared = {arg.name for arg in args}
    used = set(_PLACEHOLDER_RE.findall(run))
    unknown = sorted(used - declared)
    if unknown:
        raise ValueError(
            f"run references undeclared argument placeholder(s): {unknown!r}. Declared args: {sorted(declared)!r}",
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
    "CommandArg",
    "CommandShortcut",
    "DepSpec",
    "ExportModel",
    "HooksOverride",
    "HostBridgeSpec",
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
