"""Per-space cache of resolved space data.

The cache lives at ``${XDG_CACHE_HOME:-~/.cache}/cupli/<space-name>/cache.json``
and stores a serialised :class:`ResolvedSpace` keyed by the source ``mtime``
and SHA-256 of the YAML file. Callers must treat cache hits as opaque blobs
they can re-hydrate; misses fall through to the loader.

Used by:

- ``cupli vars``/``cupli env``/``--list`` cold paths.
- Dynamic workspace-command registration in ``cli/root.py`` — keeps cold
  startup under the typer help threshold.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from cupli.domain.models import CommandShortcut


class CachedCommandRow(TypedDict):
    """Serialized shape of one cached ``commands[<name>]`` entry."""

    container: list[str]
    run: str
    workdir: str | None
    help: str | None
    top_level: bool
    group: str | None
    execute: str
    args: list[dict[str, Any]]
    strict: bool


def _cache_root() -> Path:
    """Return ``${XDG_CACHE_HOME:-~/.cache}/cupli`` (created on demand)."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    root = Path(base) / "cupli"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_path(space_name: str) -> Path:
    """Return the per-space cache file path."""
    return _cache_root() / space_name / "cache.json"


def _file_signature(space_file: Path) -> dict[str, Any]:
    """Return a dict identifying the source file's content state."""
    try:
        stat = space_file.stat()
    except OSError:
        return {}
    digest = hashlib.sha256(space_file.read_bytes()).hexdigest()
    return {"mtime_ns": stat.st_mtime_ns, "sha256": digest, "size": stat.st_size}


CACHE_VERSION = 2
"""Cache schema version. Bumped when the serialized command shape changes."""


@dataclass(frozen=True)
class CachedCommands:
    """Lightweight cache row carrying just enough to register shortcuts.

    Attributes:
        space_name: declared name of the source space.
        commands: ``{shortcut_name: {container, run, workdir, help, top_level,
            group, execute, args}}`` where ``container`` is a list and ``args``
            a list of arg-spec dicts.
    """

    space_name: str
    commands: dict[str, CachedCommandRow]


def _normalize_command_row(row: dict[str, Any]) -> CachedCommandRow:
    """Bring a cached command row up to the current shape.

    Legacy ``version: 1`` rows stored ``container`` as a single string and had
    no ``group`` / ``execute`` / ``args`` keys. Normalising on read lets an
    unchanged old cache keep working until the source YAML is next rewritten.
    """
    container = row.get("container")
    if isinstance(container, str):
        container = [container]
    return CachedCommandRow(
        container=container or [],
        run=row.get("run") or "",
        workdir=row.get("workdir"),
        help=row.get("help"),
        top_level=bool(row.get("top_level")),
        group=row.get("group"),
        execute=row.get("execute") or "sequential",
        args=row.get("args") or [],
        strict=bool(row.get("strict")),
    )


def read_commands(space_file: Path) -> CachedCommands | None:
    """Return cached workspace commands when the cache is fresh, else None.

    Args:
        space_file: absolute path to the ``space.cupli.yaml`` source.

    Returns:
        :class:`CachedCommands` on a fresh hit; ``None`` otherwise (caller
        should fall through to a full :func:`load_space`).
    """
    sig = _file_signature(space_file)
    if not sig:
        return None
    # Scan all per-space caches and pick the one matching the path+signature.
    root = _cache_root()
    if not root.is_dir():
        return None
    for entry in root.iterdir():
        path = entry / "cache.json"
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if blob.get("source_path") != str(space_file):
            continue
        if blob.get("signature") != sig:
            continue
        commands = blob.get("commands")
        if not isinstance(commands, dict):
            return None
        normalized = {name: _normalize_command_row(row) for name, row in commands.items()}
        return CachedCommands(space_name=blob.get("space_name", ""), commands=normalized)
    return None


def write_commands(
    space_file: Path,
    space_name: str,
    commands: dict[str, CommandShortcut],
) -> None:
    """Persist a :class:`CachedCommands` snapshot for ``space_file``.

    Args:
        space_file: source path; embedded in the cache record for validation.
        space_name: declared name of the space (used as cache subdir).
        commands: ``space.commands`` dict from a validated :class:`SpaceModel`.
    """
    sig = _file_signature(space_file)
    if not sig:
        return
    path = _cache_path(space_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": CACHE_VERSION,
        "source_path": str(space_file),
        "space_name": space_name,
        "signature": sig,
        "commands": {name: _serialize_command(shortcut) for name, shortcut in commands.items()},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _serialize_command(shortcut: CommandShortcut) -> dict[str, Any]:
    """Serialize a :class:`CommandShortcut` to a JSON-safe cache row."""
    return {
        "container": list(shortcut.container),
        "run": shortcut.run,
        "workdir": shortcut.workdir,
        "help": shortcut.help,
        "top_level": shortcut.top_level,
        "group": shortcut.group,
        "execute": shortcut.execute.value,
        "args": [arg.model_dump(mode="json") for arg in shortcut.args],
        "strict": shortcut.strict,
    }


def clear_cache(space_name: str | None = None) -> None:
    """Drop cache for one space (``None`` clears the whole cache directory)."""
    root = _cache_root()
    if space_name is None:
        import shutil

        shutil.rmtree(root, ignore_errors=True)
        return
    import shutil

    shutil.rmtree(root / space_name, ignore_errors=True)


__all__ = ("CachedCommandRow", "CachedCommands", "clear_cache", "read_commands", "write_commands")
