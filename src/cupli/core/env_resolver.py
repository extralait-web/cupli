"""Variable resolution for cupli space configurations.

Implements the precedence chain described in the v2 plan:

    process env (allowlist) -> auto-vars (space) -> space.envs -> space.vars
      -> per-base: auto-vars (base) -> base.envs -> base.vars
        -> per-app: auto-vars (app) -> app.envs -> app.vars

Bash-style ``${NAME}`` and ``${NAME:-default}`` substitution is supported.
Unknown references raise ``E016`` in strict mode; otherwise they resolve to
the empty string. Circular references raise ``E014``.

This module is pure: no filesystem state beyond reading the env files it is
explicitly asked to load.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import dotenv_values

from cupli.domain.consts import VAR_REF_PATTERN
from cupli.domain.errors import CupliError

if TYPE_CHECKING:
    import re
    from collections.abc import Iterable, Mapping
    from pathlib import Path

DEFAULT_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "TERM",
    "LANG",
    "LC_ALL",
    "SSH_AUTH_SOCK",
)
"""Process-env keys forwarded into the cupli scope by default."""


def load_env_file(path: Path) -> dict[str, str]:
    """Load a dotenv-formatted file into a dict.

    Performs syntax parsing only — variable interpolation is the resolver's
    job, not the loader's. ``interpolate=False`` keeps ``${VAR}`` references
    intact so they resolve against the cupli scope (top-level / base ``vars``,
    earlier env layers) in :func:`merge_scopes`; python-dotenv's own expansion
    would otherwise collapse cupli-scope references to empty strings.

    Args:
        path: absolute path to the env file.

    Returns:
        Mapping of env keys to values. Empty when the file is missing.
    """
    if not path.exists():
        return {}
    raw = dotenv_values(path, interpolate=False)
    return {key: value for key, value in raw.items() if value is not None}


def filter_process_env(
    allowlist: Iterable[str] = DEFAULT_ENV_ALLOWLIST,
) -> dict[str, str]:
    """Return the subset of ``os.environ`` permitted into the cupli scope."""
    return {key: os.environ[key] for key in allowlist if key in os.environ}


def substitute(
    value: str,
    scope: Mapping[str, str],
    *,
    strict: bool = False,
    _seen: frozenset[str] | None = None,
) -> str:
    """Expand ``${VAR}``, ``${VAR:-default}`` and bare ``$VAR`` references.

    ``$$`` is an escape for a literal ``$`` (docker-compose convention).

    Args:
        value: string to expand.
        scope: mapping of variable names to substitutions.
        strict: when True, unknown references raise ``E016``; otherwise they
            resolve to ``""`` (or the literal default when present).
        _seen: internal recursion guard; never pass at call sites.

    Returns:
        Fully-substituted string.

    Raises:
        CupliError: ``E014`` for circular references, ``E016`` for unknown
            references in strict mode.
    """
    seen = _seen if _seen is not None else frozenset()

    def _replace(match: re.Match[str]) -> str:
        if match[0] == "$$":
            return "$"
        return _expand_match(match, scope, strict=strict, seen=seen)

    return VAR_REF_PATTERN.sub(_replace, value)


def _expand_match(
    match: re.Match[str],
    scope: Mapping[str, str],
    *,
    strict: bool,
    seen: frozenset[str],
) -> str:
    """Expand a single matched ``${...}`` or bare ``$VAR`` reference."""
    name = match["name"] or match["bare"]
    if name in seen:
        chain = " -> ".join([*seen, name])
        raise CupliError("E014", chain=chain)

    replacement = scope.get(name)
    if replacement is None:
        replacement = match["default"]
    if replacement is None:
        if strict:
            raise CupliError("E016", name=name)
        _warn_unknown_var(name)
        return ""

    if "$" not in replacement:
        return replacement
    return substitute(replacement, scope, strict=strict, _seen=seen | {name})


def _warn_unknown_var(name: str) -> None:
    """Emit a yellow warning for an undefined ``${VAR}`` reference.

    Pure stderr — does NOT raise. Run cupli with ``--strict-vars`` to turn
    unknown references into hard ``E016`` errors instead.
    """
    from cupli.utils.console import warn

    warn(f"unknown ${{{name}}} resolved to empty string; pass --strict-vars to make this an error.")


def merge_scopes(
    layers: Iterable[Mapping[str, str]],
    *,
    strict: bool = False,
) -> dict[str, str]:
    """Merge variable layers left-to-right with substitution.

    Each successive layer overrides earlier values. Within a layer, values
    may reference variables already accumulated in earlier layers.

    Args:
        layers: iterable of mappings, evaluated in declaration order.
        strict: forwarded to :func:`substitute`.

    Returns:
        Combined scope dict.

    Raises:
        CupliError: ``E014`` / ``E016`` from :func:`substitute`.
    """
    scope: dict[str, str] = {}
    for layer in layers:
        for name, raw_value in layer.items():
            scope[name] = substitute(raw_value, scope, strict=strict)
    return scope


def check_no_shadow(
    user_vars: Mapping[str, str],
    reserved: Iterable[str],
) -> None:
    """Raise ``E015`` when ``user_vars`` contains any reserved name.

    Args:
        user_vars: user-declared variable mapping (space/base/app/mount.vars).
        reserved: collection of names treated as reserved auto-vars.
    """
    reserved_set = frozenset(reserved)
    for name in user_vars:
        if name in reserved_set:
            raise CupliError("E015", name=name)


__all__ = (
    "DEFAULT_ENV_ALLOWLIST",
    "check_no_shadow",
    "filter_process_env",
    "load_env_file",
    "merge_scopes",
    "substitute",
)
