"""YAML parser for ``space.cupli.yaml``.

Two-step pipeline:

1. Load via ``ruamel.yaml`` in round-trip mode so every key/item carries its
   source ``(line, column)`` position.
2. Convert the ``CommentedMap``/``CommentedSeq`` tree into plain dicts/lists
   (preserving order) and validate with :class:`cupli.domain.models.SpaceModel`.

The position table from step 1 is returned alongside the model so callers can
render validation failures with the offending source location.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from cupli.domain.errors import CupliError, ValidationFailure
from cupli.domain.models import SpaceModel
from cupli.domain.plan import LineMarks

if TYPE_CHECKING:
    from pathlib import Path


def parse_space_file(path: Path) -> tuple[SpaceModel, LineMarks]:
    """Parse a space YAML file into a validated model + source position map.

    Args:
        path: absolute path to the space yaml file.

    Returns:
        Tuple ``(model, marks)`` where ``model`` is the validated
        :class:`SpaceModel` and ``marks`` maps pydantic ``loc`` tuples to
        ``(line, column)`` positions in the source file.

    Raises:
        CupliError: ``E001`` when ``path`` does not exist, ``E003`` when the
            file is empty or comment-only, ``E004`` when YAML syntax is invalid.
        ValidationFailure: when the document fails schema validation.
    """
    if not path.exists():
        raise CupliError("E001", path=str(path))

    raw = _load_yaml(path)
    if raw is None:
        raise CupliError("E003", path=str(path))

    marks = LineMarks(file=path, items=_extract_marks(raw, ()))
    plain = _to_plain(raw)

    try:
        model = SpaceModel.model_validate(plain)
    except ValidationError as exc:
        raise ValidationFailure(file=path, errors_list=exc.errors(), marks=marks) from exc

    return model, marks


def _load_yaml(path: Path) -> Any:
    """Read and parse ``path`` with round-trip semantics."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        with path.open("r", encoding="utf-8") as fp:
            return yaml.load(fp)
    except YAMLError as exc:
        line, col = _yaml_error_location(exc)
        raise CupliError("E004", path=str(path), line=line, col=col, message=str(exc)) from exc


def _yaml_error_location(exc: YAMLError) -> tuple[int, int]:
    """Best-effort extraction of (line, column) from a ruamel YAMLError."""
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    if mark is None:
        return 0, 0
    return mark.line + 1, mark.column + 1


def _extract_marks(node: Any, path: tuple[Any, ...]) -> dict[tuple[Any, ...], tuple[int, int]]:
    """Walk a ruamel tree and collect a loc-tuple → (line, col) mapping."""
    marks: dict[tuple[Any, ...], tuple[int, int]] = {}
    if isinstance(node, Mapping):
        _extract_map_marks(node, path, marks)
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
        _extract_seq_marks(node, path, marks)
    return marks


def _extract_map_marks(
    node: Mapping[Any, Any],
    path: tuple[Any, ...],
    marks: dict[tuple[Any, ...], tuple[int, int]],
) -> None:
    """Collect key positions and recurse into mapping values."""
    lc = getattr(node, "lc", None)
    for key in node:
        if lc is not None:
            mark = _safe_key_mark(lc, key)
            if mark is not None:
                marks[(*path, key)] = mark
        marks.update(_extract_marks(node[key], (*path, key)))


def _extract_seq_marks(
    node: Sequence[Any],
    path: tuple[Any, ...],
    marks: dict[tuple[Any, ...], tuple[int, int]],
) -> None:
    """Collect item positions and recurse into sequence elements."""
    lc = getattr(node, "lc", None)
    for index, item in enumerate(node):
        if lc is not None:
            mark = _safe_item_mark(lc, index)
            if mark is not None:
                marks[(*path, index)] = mark
        marks.update(_extract_marks(item, (*path, index)))


def _safe_key_mark(lc: Any, key: Any) -> tuple[int, int] | None:
    """Wrap ``lc.key(key)`` because ruamel sometimes raises for top-level keys."""
    try:
        position = lc.key(key)
    except (KeyError, AttributeError, TypeError):
        return None
    if position is None:
        return None
    return position[0] + 1, position[1] + 1


def _safe_item_mark(lc: Any, index: int) -> tuple[int, int] | None:
    """Wrap ``lc.item(index)`` defensively."""
    try:
        position = lc.item(index)
    except (KeyError, AttributeError, TypeError, IndexError):
        return None
    if position is None:
        return None
    return position[0] + 1, position[1] + 1


def _to_plain(value: Any) -> Any:
    """Convert ``CommentedMap``/``CommentedSeq`` into plain dict/list.

    Preserves insertion order (regular dicts do in Python 3.7+).
    """
    if isinstance(value, Mapping):
        return {key: _to_plain(value[key]) for key in value}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_to_plain(item) for item in value]
    return value


__all__ = ("parse_space_file",)
