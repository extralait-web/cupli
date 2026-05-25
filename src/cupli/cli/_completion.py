"""Shell-completion callbacks shared across the typer surface.

Every callback returns a list of candidate strings that ``startswith`` the
incomplete token. Loading the space is best-effort — on any error the
callback returns an empty list so completion never breaks the prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cupli.core.loader import ResolvedSpace


def _resolved_space_quiet() -> ResolvedSpace | None:
    """Detect + load the effective space without ANY side effects.

    Returns ``None`` on any error so completion stays silent.
    """
    from pathlib import Path

    from cupli.core import registry
    from cupli.core.loader import load_space

    try:
        detected = registry.detect_current_space(Path.cwd())
        return load_space(detected.path, auto_register=False, auto_cache=False)
    except Exception:
        return None


def complete_space_names(incomplete: str) -> list[str]:
    """Complete every registered space name."""
    from cupli.core import registry
    from cupli.domain.errors import CupliError

    try:
        known = registry.list_known_spaces()
    except CupliError:
        return []
    return [name for name in sorted(known) if name.startswith(incomplete)]


def complete_shortcut_names(incomplete: str) -> list[str]:
    """Complete every ``commands.<name>`` entry declared in the current space.

    Reads from ``~/.cache/cupli/<space>/cache.json`` when available (fast
    path); falls back to a fresh load when the cache is cold or stale.
    """
    from pathlib import Path

    from cupli.core import cache, registry

    try:
        detected = registry.detect_current_space(Path.cwd())
    except Exception:
        return []
    cached = cache.read_commands(detected.path)
    if cached is not None:
        return [name for name in sorted(cached.commands) if name.startswith(incomplete)]
    resolved = _resolved_space_quiet()
    if resolved is None:
        return []
    return [name for name in sorted(resolved.space.commands) if name.startswith(incomplete)]


def complete_service_names(incomplete: str) -> list[str]:
    """Complete docker-compose service names (``apps[*].service`` or app key)."""
    resolved = _resolved_space_quiet()
    if resolved is None:
        return []
    names = {app.primary_service_name(name) for name, app in resolved.space.apps.items()}
    return sorted(name for name in names if name.startswith(incomplete))


def complete_app_names(incomplete: str) -> list[str]:
    """Complete app keys from the current space (for ``cupli with -c``)."""
    resolved = _resolved_space_quiet()
    if resolved is None:
        return []
    return sorted(name for name in resolved.space.apps if name.startswith(incomplete))


def complete_mount_names(incomplete: str) -> list[str]:
    """Complete declared mount names (``mounts[*]``)."""
    resolved = _resolved_space_quiet()
    if resolved is None:
        return []
    return sorted(name for name in resolved.space.mounts if name.startswith(incomplete))


def complete_tag_names(incomplete: str) -> list[str]:
    """Complete every tag declared across ``apps[*].tags``."""
    resolved = _resolved_space_quiet()
    if resolved is None:
        return []
    tags: set[str] = set()
    for app in resolved.space.apps.values():
        tags.update(app.tags)
    return sorted(tag for tag in tags if tag.startswith(incomplete))


def complete_hook_scope(incomplete: str) -> list[str]:
    """Complete the fixed ``--scope`` choices for the hooks command."""
    return [scope for scope in ("all", "apps", "bases", "mounts") if scope.startswith(incomplete)]


def complete_hook_targets(incomplete: str) -> list[str]:
    """Complete target names across ``apps`` / ``bases`` / ``mounts``."""
    resolved = _resolved_space_quiet()
    if resolved is None:
        return []
    names: set[str] = set()
    names.update(resolved.space.apps)
    names.update(resolved.space.bases)
    names.update(resolved.space.mounts)
    return sorted(name for name in names if name.startswith(incomplete))


def complete_error_codes(incomplete: str) -> list[str]:
    """Complete every known cupli error code (``E001`` … ``E0NN``)."""
    from cupli.domain.errors import ERRORS

    return sorted(code for code in ERRORS if code.startswith(incomplete.upper()))


def complete_branch_map(incomplete: str) -> list[str]:
    """Complete ``name=`` candidates for ``--map`` options on git checkout.

    Returns the component name with a trailing ``=`` so the shell stops at the
    point where the user has to type the branch.
    """
    if "=" in incomplete:
        return []
    resolved = _resolved_space_quiet()
    if resolved is None:
        return []
    names: set[str] = set()
    names.update(resolved.space.apps)
    names.update(resolved.space.bases)
    names.update(resolved.space.mounts)
    return sorted(f"{name}=" for name in names if name.startswith(incomplete))


__all__ = (
    "complete_app_names",
    "complete_branch_map",
    "complete_error_codes",
    "complete_hook_scope",
    "complete_hook_targets",
    "complete_mount_names",
    "complete_service_names",
    "complete_shortcut_names",
    "complete_space_names",
    "complete_tag_names",
)
