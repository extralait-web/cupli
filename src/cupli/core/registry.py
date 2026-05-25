"""Known-spaces registry with a persistent active-space slot.

The registry lives at ``${XDG_CONFIG_HOME:-~/.config}/cupli/spaces.json`` and
stores:

- A ``spaces`` map from name to absolute path of a ``space.cupli.yaml``.
- An ``active`` name — the workspace ``cupli`` falls back to when ``cwd``
  is not inside any registered space.

The on-disk file uses a versioned envelope:
``{"v": 2, "active": str | None, "spaces": {name: path}}``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from cupli.domain.consts import CUPLI_SPACE_FILE_PATTERN
from cupli.domain.errors import CupliError
from cupli.utils.path import create_file, read_json, write_json

REGISTRY_VERSION = 2


@dataclass(frozen=True)
class DetectedSpace:
    """Result of :func:`detect_current_space`.

    Attributes:
        name: registry-known name, ``None`` when the space was discovered
            from a fresh ``space.cupli.yaml`` file in ``cwd``.
        path: absolute path to the space YAML file.
        is_known: True when the space is already in the registry.
    """

    name: str | None
    path: Path
    is_known: bool


def spaces_registry_path() -> Path:
    """Return the absolute path of the per-user spaces registry JSON file.

    Resolution order:

    1. ``$CUPLI_SPACES_FILE`` — explicit override, used by tests.
    2. ``${XDG_CONFIG_HOME:-~/.config}/cupli/spaces.json``.
    """
    override = os.environ.get("CUPLI_SPACES_FILE")
    if override:
        return Path(override).resolve()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base).resolve() / "cupli" / "spaces.json"


# --- state helpers ---------------------------------------------------------


def _empty_state() -> dict[str, Any]:
    """Return a fresh registry document."""
    return {"v": REGISTRY_VERSION, "active": None, "spaces": {}}


def _load_state() -> dict[str, Any]:
    """Read the registry, creating it on demand."""
    path = spaces_registry_path()
    if not path.exists():
        _create_registry_file(path)
    raw = cast("dict[str, Any]", read_json(path))
    if not (isinstance(raw.get("v"), int) and isinstance(raw.get("spaces"), dict)):
        return _empty_state()
    raw.setdefault("active", None)
    return raw


def _save_state(state: dict[str, Any]) -> None:
    """Persist ``state`` to the registry file."""
    write_json(spaces_registry_path(), state)


def _create_registry_file(path: Path) -> None:
    """Initialise an empty registry file at ``path``."""
    create_file(path)
    write_json(path, _empty_state())


# --- space CRUD ------------------------------------------------------------


def list_known_spaces() -> dict[str, Path]:
    """Return ``{name: path}`` for every registered space."""
    state = _load_state()
    spaces = state.get("spaces") or {}
    return {key: Path(value) for key, value in spaces.items()}


def get_space_path(name: str) -> Path:
    """Return the registered path for ``name``.

    Raises:
        CupliError: ``E020`` when ``name`` is not registered.
    """
    spaces = list_known_spaces()
    if name not in spaces:
        raise CupliError("E020", name=name)
    return spaces[name]


def add_space(name: str, path: Path) -> None:
    """Register ``name -> path`` in the registry (idempotent on equal entries).

    Raises:
        CupliError: ``E019`` when ``name`` already points to a different path.
    """
    state = _load_state()
    spaces = state.setdefault("spaces", {})
    existing = spaces.get(name)
    if existing is not None and Path(existing) != path:
        raise CupliError("E019", name=name, path=str(existing))
    if existing is not None:
        return
    spaces[name] = str(path)
    _save_state(state)


def remove_space(name: str) -> None:
    """Drop ``name`` from the registry. Clears the active slot if it matched.

    Raises:
        CupliError: ``E020`` when ``name`` is not registered.
    """
    state = _load_state()
    spaces = state.setdefault("spaces", {})
    if name not in spaces:
        raise CupliError("E020", name=name)
    del spaces[name]
    if state.get("active") == name:
        state["active"] = None
    _save_state(state)


def rename_space(old: str, new: str) -> None:
    """Rename a registry entry; rewires the active slot when it points at ``old``.

    Raises:
        CupliError: ``E020`` when ``old`` is missing, ``E019`` when ``new`` is taken.
    """
    state = _load_state()
    spaces = state.setdefault("spaces", {})
    if old not in spaces:
        raise CupliError("E020", name=old)
    if new in spaces:
        raise CupliError("E019", name=new, path=str(spaces[new]))
    spaces[new] = spaces.pop(old)
    if state.get("active") == old:
        state["active"] = new
    _save_state(state)


# --- active selection ------------------------------------------------------


def get_active_space() -> str | None:
    """Return the persistent active-space name, or ``None`` when unset."""
    state = _load_state()
    active = state.get("active")
    return active if isinstance(active, str) else None


def set_active_space(name: str | None) -> None:
    """Set (or clear when ``None``) the persistent active space.

    Raises:
        CupliError: ``E020`` when ``name`` is not registered.
    """
    state = _load_state()
    if name is not None and name not in state.get("spaces", {}):
        raise CupliError("E020", name=name)
    state["active"] = name
    _save_state(state)


# --- detection -------------------------------------------------------------


def detect_current_space(cwd: Path) -> DetectedSpace:
    """Detect the effective space for the given working directory.

    Resolution order (active is *sticky* — an explicit ``workspace select``
    wins over wherever you happen to ``cd``):

    1. Persistent ``active`` selection from the registry, if set.
    2. Registered space whose root directory is the longest prefix of ``cwd``.
    3. ``*.cupli.ya?ml`` file scanned directly from ``cwd``.

    To go back to cwd-driven detection, run ``cupli workspace select --clear``.

    Raises:
        CupliError: ``E001`` when nothing matches.
    """
    active = get_active_space()
    if active is not None:
        return DetectedSpace(name=active, path=get_space_path(active), is_known=True)

    known = list_known_spaces()
    found = _longest_matching_space(cwd, known)
    if found is not None:
        name, path = found
        return DetectedSpace(name=name, path=path, is_known=True)

    candidate = _scan_cwd_for_space_file(cwd)
    if candidate is not None:
        return DetectedSpace(name=None, path=candidate, is_known=False)

    raise CupliError("E001", path=str(cwd))


# --- helpers ---------------------------------------------------------------


def _longest_matching_space(
    cwd: Path,
    known: dict[str, Path],
) -> tuple[str, Path] | None:
    """Return the registered space whose root is the longest prefix of ``cwd``."""
    cwd_str = str(cwd)
    best: tuple[str, Path] | None = None
    best_len = -1
    for name, path in known.items():
        root_str = str(path.parent)
        if not _path_starts_with(cwd_str, root_str):
            continue
        if len(root_str) > best_len:
            best = (name, path)
            best_len = len(root_str)
    return best


def _path_starts_with(cwd_str: str, root_str: str) -> bool:
    r"""True when ``cwd_str`` is exactly ``root_str`` or a child path.

    Path separators differ across platforms (``/`` on POSIX, ``\`` on
    Windows), so both are accepted when delimiting the parent from its
    children.
    """
    if cwd_str == root_str:
        return True
    trimmed = root_str.rstrip("/\\")
    return cwd_str.startswith((trimmed + os.sep, trimmed + "/"))


def _scan_cwd_for_space_file(cwd: Path) -> Path | None:
    """Return the first ``*.cupli.ya?ml`` file in ``cwd``."""
    if not cwd.is_dir():
        return None
    for entry in cwd.iterdir():
        if CUPLI_SPACE_FILE_PATTERN.match(entry.name):
            return entry
    return None


__all__ = (
    "DetectedSpace",
    "REGISTRY_VERSION",
    "add_space",
    "detect_current_space",
    "get_active_space",
    "get_space_path",
    "list_known_spaces",
    "remove_space",
    "rename_space",
    "set_active_space",
    "spaces_registry_path",
)
