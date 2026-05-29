"""Generate ``space.schema.json`` from the Pydantic ``SpaceModel``.

Run with ``uv run python scripts/generate_schema.py`` (or via ``make schema``).
The output lives at ``space.schema.json`` in the repo root and is referenced
by every example workspace via a ``# yaml-language-server: $schema=…`` line.

Post-processing:

* Adds well-known docker-compose service-level fields to ``ServiceOverride``
  so editors offer them as completions next to cupli's own ``vars`` /
  ``ports``. ``additionalProperties: true`` is preserved so the schema still
  accepts anything compose understands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cupli.domain.models import SpaceModel


COMPOSE_SERVICE_FIELDS: dict[str, dict[str, Any]] = {
    "image": {"type": "string", "description": "Image to pull or build."},
    "build": {
        "description": "Build context: a string path, or a mapping with `context`, `dockerfile`, `args`, etc.",
        "anyOf": [
            {"type": "string"},
            {
                "type": "object",
                "properties": {
                    "context": {"type": "string"},
                    "dockerfile": {"type": "string"},
                    "target": {"type": "string"},
                    "args": {"type": ["object", "array"]},
                    "labels": {"type": ["object", "array"]},
                    "cache_from": {"type": "array", "items": {"type": "string"}},
                    "cache_to": {"type": "array", "items": {"type": "string"}},
                    "network": {"type": "string"},
                    "platforms": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            },
        ],
    },
    "command": {"description": "Override the default command.", "anyOf": [{"type": "string"}, {"type": "array"}]},
    "entrypoint": {"description": "Override the default entrypoint.", "anyOf": [{"type": "string"}, {"type": "array"}]},
    "environment": {
        "description": "Environment variables. Map or list of KEY=VALUE entries.",
        "anyOf": [{"type": "object", "additionalProperties": {"type": ["string", "number", "boolean", "null"]}}, {"type": "array", "items": {"type": "string"}}],
    },
    "env_file": {
        "description": "Path(s) to .env files merged into `environment`.",
        "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
    },
    "volumes": {
        "type": "array",
        "description": "Bind mounts / volumes (string or long-form mapping).",
        "items": {"anyOf": [{"type": "string"}, {"type": "object"}]},
    },
    "depends_on": {
        "description": "Service dependencies. List of names or map of `name → { condition, restart, required }`.",
        "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "object"}],
    },
    "healthcheck": {
        "type": "object",
        "description": "Container healthcheck spec (test, interval, timeout, retries, start_period).",
        "additionalProperties": True,
    },
    "restart": {
        "type": "string",
        "description": "Restart policy.",
        "enum": ["no", "always", "on-failure", "unless-stopped"],
    },
    "ports": {
        "type": "array",
        "description": "Compose port mappings (short or long form). Cupli's `ports` field at app level replaces these.",
        "items": {"anyOf": [{"type": "string"}, {"type": "object"}]},
    },
    "expose": {
        "type": "array",
        "description": "Ports exposed without publishing.",
        "items": {"type": ["string", "number"]},
    },
    "networks": {
        "description": "Networks to attach. List or map.",
        "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "object"}],
    },
    "container_name": {"type": "string", "description": "Container name (cupli defaults to `<space>-<service>`)."},
    "hostname": {"type": "string"},
    "user": {"type": "string"},
    "working_dir": {"type": "string"},
    "labels": {"description": "Labels.", "anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "string"}}]},
    "logging": {"type": "object", "additionalProperties": True},
    "ulimits": {"type": "object", "additionalProperties": True},
    "cap_add": {"type": "array", "items": {"type": "string"}},
    "cap_drop": {"type": "array", "items": {"type": "string"}},
    "devices": {"type": "array", "items": {"type": "string"}},
    "dns": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "extra_hosts": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "object"}]},
    "tmpfs": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "stop_signal": {"type": "string"},
    "stop_grace_period": {"type": "string"},
    "shm_size": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
    "privileged": {"type": "boolean"},
    "init": {"type": "boolean"},
    "tty": {"type": "boolean"},
    "stdin_open": {"type": "boolean"},
    "read_only": {"type": "boolean"},
    "deploy": {"type": "object", "additionalProperties": True},
    "profiles": {"type": "array", "items": {"type": "string"}},
    "platform": {"type": "string"},
    "pull_policy": {"type": "string"},
    "secrets": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "object"}]}},
    "configs": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "object"}]}},
    # --- resource limits / cgroup ---
    "cpus": {"anyOf": [{"type": "number"}, {"type": "string"}], "description": "Number of CPUs to allocate."},
    "cpu_count": {"type": "integer"},
    "cpu_percent": {"type": "number"},
    "cpu_shares": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    "cpu_quota": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    "cpu_period": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    "cpuset": {"type": "string"},
    "mem_limit": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Memory limit (e.g. `512m`)."},
    "mem_reservation": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
    "mem_swappiness": {"type": "integer"},
    "memswap_limit": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
    "pids_limit": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    "oom_kill_disable": {"type": "boolean"},
    "oom_score_adj": {"type": "integer"},
    "cgroup": {"type": "string", "enum": ["host", "private"]},
    "cgroup_parent": {"type": "string"},
    "blkio_config": {"type": "object", "additionalProperties": True},
    "storage_opt": {"type": "object", "additionalProperties": True},
    "gpus": {"anyOf": [{"type": "string"}, {"type": "array"}], "description": "GPU reservations (`all` or a list)."},
    # --- networking ---
    "network_mode": {"type": "string", "description": "`bridge` / `host` / `none` / `service:<name>` / `container:<name>`."},
    "links": {"type": "array", "items": {"type": "string"}},
    "external_links": {"type": "array", "items": {"type": "string"}},
    "dns_opt": {"type": "array", "items": {"type": "string"}},
    "dns_search": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "mac_address": {"type": "string"},
    "domainname": {"type": "string"},
    # --- process / namespaces ---
    "pid": {"type": "string"},
    "ipc": {"type": "string"},
    "uts": {"type": "string"},
    "userns_mode": {"type": "string"},
    "isolation": {"type": "string"},
    "runtime": {"type": "string"},
    "group_add": {"type": "array", "items": {"type": ["string", "number"]}},
    "security_opt": {"type": "array", "items": {"type": "string"}},
    "device_cgroup_rules": {"type": "array", "items": {"type": "string"}},
    "sysctls": {
        "description": "Kernel parameters. Map or list of KEY=VALUE entries.",
        "anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "string"}}],
    },
    "credential_spec": {"type": "object", "additionalProperties": True},
    "use_api_socket": {"type": "boolean"},
    # --- volumes / scaling / lifecycle ---
    "volumes_from": {"type": "array", "items": {"type": "string"}},
    "scale": {"type": "integer", "description": "Default number of replicas for this service."},
    "annotations": {"anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "string"}}]},
    "attach": {"type": "boolean"},
    "label_file": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "extends": {
        "description": "Inherit from another service (string name or `{file, service}` mapping).",
        "anyOf": [{"type": "string"}, {"type": "object", "additionalProperties": True}],
    },
    "develop": {"type": "object", "additionalProperties": True, "description": "`watch` rules for `docker compose watch`."},
    "post_start": {"type": "array", "items": {"type": "object"}, "description": "Lifecycle hooks run after start."},
    "pre_stop": {"type": "array", "items": {"type": "object"}, "description": "Lifecycle hooks run before stop."},
}
"""Common docker-compose service-level fields surfaced as completions.

Mirrors the service attributes of the compose-spec
(https://github.com/compose-spec/compose-spec). ``additionalProperties: true``
stays in place on ``ServiceOverride``, so anything omitted here is still
accepted — these entries only power editor completion and hover docs.
"""


STRING_OR_LIST_FIELDS: frozenset[str] = frozenset({
    "envs",
    "composes",
    "ports",
    "bases",
    "hosted_in",
    "tags",
    "ignore",
    "before_start",
    "after_start",
    "after_stop",
    "container",
    "refresh_on",
})
"""Fields whose Pydantic side accepts both a bare string and a list (auto-wrap).

The schema must mirror that — otherwise editors flag valid YAML like
``tags: backend`` as a type error.
"""


def main() -> None:
    """Dump SpaceModel JSON Schema to ``space.schema.json``."""
    schema = SpaceModel.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "cupli space"
    schema["description"] = "Schema for `space.cupli.yaml` — the cupli workspace specification."

    _allow_string_or_list(schema)
    _augment_service_override(schema)

    out_path = Path(__file__).resolve().parent.parent / "space.schema.json"
    out_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


def _allow_string_or_list(schema: dict[str, Any]) -> None:
    """Patch list-valued and deps fields to accept their permissive Pydantic forms.

    * Fields in :data:`STRING_OR_LIST_FIELDS` are rewritten to ``anyOf:
      [{string}, {array as-was}]`` — matches ``_wrap_str_as_list``.
    * The ``deps`` field is rewritten to ``anyOf: [{array of names},
      {object as-was}]`` — matches ``_deps_to_dict``.
    """
    for node in (schema, *(d for d in (schema.get("$defs") or {}).values())):
        _patch_properties(node)


def _patch_properties(node: Any) -> None:
    """Walk ``properties`` of a single object node, rewriting list / deps fields."""
    if not isinstance(node, dict):
        return
    properties = node.get("properties")
    if not isinstance(properties, dict):
        return
    for name, definition in properties.items():
        if name in STRING_OR_LIST_FIELDS:
            properties[name] = _wrap_anyof(definition, _scalar_string_alt())
        elif name == "deps":
            properties[name] = _deps_schema(definition)
        elif name == "services":
            properties[name] = _wrap_anyof(definition, _services_list_alt())
        elif name == "run":
            properties[name] = _wrap_anyof(definition, _string_array_alt())
        elif name == "args":
            properties[name] = _wrap_anyof(definition, _string_array_alt())


def _wrap_anyof(definition: dict[str, Any], alternative: dict[str, Any]) -> dict[str, Any]:
    """Return ``{anyOf: [alternative, original]}`` preserving title/description/default."""
    wrapper: dict[str, Any] = {}
    for top_level in ("title", "description", "default"):
        if top_level in definition:
            wrapper[top_level] = definition[top_level]
    base_shape = {k: v for k, v in definition.items() if k not in {"title", "description", "default"}}
    wrapper["anyOf"] = [alternative, base_shape if base_shape else {}]
    return wrapper


def _scalar_string_alt() -> dict[str, Any]:
    """The ``string`` alternative for ``_wrap_str_as_list``-style fields."""
    return {"type": "string"}


def _string_array_alt() -> dict[str, Any]:
    """The ``array of strings`` alternative for ``run`` lines and ``args`` shorthand."""
    return {"type": "array", "items": {"type": "string"}}


def _deps_array_alt() -> dict[str, Any]:
    """The ``array of dependency names`` alternative for ``_deps_to_specs``-style fields."""
    return {
        "type": "array",
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[A-Za-z][A-Za-z0-9_-]*$",
        },
    }


def _deps_schema(definition: dict[str, Any]) -> dict[str, Any]:
    """Build the full ``deps`` schema covering every accepted shorthand.

    Accepts: list-of-names, or an object whose value is any of {null, condition
    string, list of mode-tag strings, full :class:`DepSpec` object}. The
    ``DepSpec`` ref comes from the pydantic-generated ``$defs``.
    """
    wrapper: dict[str, Any] = {}
    for top_level in ("title", "description", "default"):
        if top_level in definition:
            wrapper[top_level] = definition[top_level]
    wrapper["anyOf"] = [
        _deps_array_alt(),
        {
            "type": "object",
            "additionalProperties": {
                "anyOf": [
                    {"type": "null"},
                    {"type": "string", "enum": [c.value for c in __dep_conditions()]},
                    {"type": "array", "items": {"type": "string", "enum": [m.value for m in __dep_modes()]}},
                    {"$ref": "#/$defs/DepSpec"},
                ],
            },
        },
    ]
    return wrapper


def __dep_conditions() -> Any:
    """Defer import so :mod:`cupli` stays light at module load."""
    from cupli.domain.enums import DepCondition

    return DepCondition


def __dep_modes() -> Any:
    """Defer import so :mod:`cupli` stays light at module load."""
    from cupli.domain.enums import DepMode

    return DepMode


def _services_list_alt() -> dict[str, Any]:
    """The ``array of service names`` alternative for ``_services_list_to_dict``-style fields."""
    return {
        "type": "array",
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[A-Za-z][A-Za-z0-9_-]*$",
        },
    }


def _augment_service_override(schema: dict[str, Any]) -> None:
    """Add docker-compose service-level fields to the ServiceOverride definition.

    ``additionalProperties: true`` stays in place so anything else compose
    understands is still allowed — these explicit entries just power editor
    completions and inline hover docs.
    """
    defs = schema.get("$defs") or {}
    target = defs.get("ServiceOverride")
    if target is None:
        return
    properties = target.setdefault("properties", {})
    for name, definition in COMPOSE_SERVICE_FIELDS.items():
        properties.setdefault(name, definition)


if __name__ == "__main__":
    main()
