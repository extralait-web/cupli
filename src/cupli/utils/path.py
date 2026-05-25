"""Filesystem helpers.

Pure side-effects only — no logging, no rich console. Callers handle
formatting at the CLI layer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cupli.utils.json import CupliJsonEncoder

if TYPE_CHECKING:
    from pathlib import Path


def create_dir(path: Path | str) -> None:
    """Create a directory with mode ``0o755`` (parents included) if missing."""
    from pathlib import Path as _Path

    target = _Path(path)
    if not target.exists():
        target.mkdir(parents=True, mode=0o755)


def create_file(path: Path | str) -> None:
    """Touch a file with mode ``0o755`` if missing, creating parents as needed."""
    from pathlib import Path as _Path

    target = _Path(path)
    if not target.exists():
        target.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
        target.touch(mode=0o755)


def rename_file(path: Path, name: str) -> None:
    """Rename ``path`` in place to ``name`` (within the same parent directory)."""
    path.rename(path.parent.joinpath(name))


def write_text(path: Path | str, data: str) -> None:
    """Write UTF-8 text to ``path``."""
    from pathlib import Path as _Path

    _Path(path).write_text(data, encoding="utf-8")


def read_text(path: Path | str) -> str:
    """Read UTF-8 text from ``path`` (trailing whitespace stripped)."""
    from pathlib import Path as _Path

    return _Path(path).read_text(encoding="utf-8").strip()


def write_json(path: Path | str, data: dict | list) -> None:
    """Write ``data`` to ``path`` as pretty JSON."""
    write_text(path, json.dumps(data, cls=CupliJsonEncoder, indent=4))


def read_json(path: Path | str) -> dict | list:
    """Read a JSON document from ``path``."""
    return json.loads(read_text(path))


def absolutize(path: Path | str, *, anchor: Path) -> Path:
    """Return ``path`` absolutised against ``anchor`` when relative."""
    from pathlib import Path as _Path

    candidate = _Path(path)
    if candidate.is_absolute():
        return candidate
    return (anchor / candidate).resolve()


__all__ = (
    "absolutize",
    "create_dir",
    "create_file",
    "read_json",
    "read_text",
    "rename_file",
    "write_json",
    "write_text",
)
