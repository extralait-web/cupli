"""Decorators and helpers that convert :class:`CupliError` into a clean CLI exit."""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, ParamSpec, TypeVar

import typer

from cupli.domain.errors import CupliError, ValidationFailure, error_spec
from cupli.utils.console import console

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
R = TypeVar("R")


def print_cupli_error(exc: CupliError) -> None:
    """Render a :class:`CupliError` in the cupli house style.

    Pattern: ``CODE  Title`` on the first line, message on the second,
    hint on the third (when present). For :class:`ValidationFailure`,
    every pydantic field error is listed with file:line:col when known.
    """
    spec = error_spec(exc.code)
    body = str(exc)
    if ": " in body:
        body = body.split(": ", 1)[1]
    console.print(f"[red bold]{exc.code}[/red bold] [red]{spec['title']}[/red]")
    console.print(f"  {body}")
    if isinstance(exc, ValidationFailure):
        _print_validation_details(exc)
    if spec["hint"]:
        console.print(f"  [yellow]hint:[/yellow] {spec['hint']}")


def _print_validation_details(exc: ValidationFailure) -> None:
    """Render every pydantic field error of a :class:`ValidationFailure`.

    Each line is ``  • <loc>: <msg> (at <file>:<line>:<col>)`` when source
    marks are available, otherwise it drops the position suffix.
    """
    for item in exc.errors_list:
        loc = item.get("loc") or ()
        msg = item.get("msg", "invalid")
        loc_str = ".".join(str(part) for part in loc) or "<root>"
        position = _position_for(exc, tuple(loc))
        if position is not None:
            line, col = position
            console.print(
                f"  • [cyan]{loc_str}[/cyan]: {msg} ([dim]{exc.file}:{line}:{col}[/dim])",
            )
        else:
            console.print(f"  • [cyan]{loc_str}[/cyan]: {msg}")


def _position_for(exc: ValidationFailure, loc: tuple) -> tuple[int, int] | None:
    """Return the (line, col) tuple for ``loc`` or its nearest ancestor."""
    if exc.marks is None:
        return None
    items = exc.marks.items
    while loc:
        position = items.get(loc)
        if position is not None:
            return position
        loc = loc[:-1]
    return None


def suppress_known_exceptions(fn: Callable[P, R]) -> Callable[P, R]:
    """Decorator: render :class:`CupliError` and exit with code 1.

    Other exceptions propagate untouched so that bugs in cupli still surface
    a Python traceback in DEBUG runs.
    """

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except CupliError as exc:
            print_cupli_error(exc)
            raise typer.Exit(code=1) from exc

    return wrapper


__all__ = ("print_cupli_error", "suppress_known_exceptions")
