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
}
"""Common docker-compose service-level fields surfaced as completions."""


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
            properties[name] = _wrap_anyof(definition, _deps_array_alt())
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
    """The ``array of dependency names`` alternative for ``_deps_to_dict``-style fields."""
    return {
        "type": "array",
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[A-Za-z][A-Za-z0-9_-]*$",
        },
    }


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
