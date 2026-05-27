"""Tests for dynamic typed registration of top-level command shortcuts.

Mirrors what ``cli/root.py:_wire_typed_shortcut`` does: a synthetic signature
built from declared args is registered as a typer command, exposing real
arguments/options in ``--help`` and dispatching parsed values.
"""

from __future__ import annotations

import click
import typer
from typer.testing import CliRunner

from cupli.cli._shortcuts import build_signature, specs_from_cache


def _typed_app(captured: dict[str, object]) -> typer.Typer:
    """Build a typer app with a dynamically typed ``migrate`` command."""
    rows = [
        {"name": "app", "type": "str", "required": True},
        {"name": "fake", "type": "bool"},
        {"name": "level", "type": "str", "option": True, "short": "l", "default": "info"},
    ]
    signature, annotations = build_signature(specs_from_cache(rows))

    def _runner(ctx: typer.Context, **values: object) -> None:
        _ = ctx
        captured.update(values)

    _runner.__signature__ = signature  # type: ignore[attr-defined]
    _runner.__annotations__ = annotations

    app = typer.Typer(add_completion=False)
    app.command(name="migrate", rich_help_panel="Database")(_runner)
    app.command(name="noop")(lambda: None)
    return app


def _migrate_command(app: typer.Typer) -> click.Command:
    """Return the built click command for the ``migrate`` shortcut.

    Introspecting the click command (rather than the rendered ``--help`` text)
    keeps these assertions independent of color/width rendering, which differs
    between local runs and CI (``FORCE_COLOR`` / ``COLUMNS``).
    """
    group = typer.main.get_command(app)
    assert isinstance(group, click.Group)
    return group.commands["migrate"]


def test_typed_shortcut_exposes_args_and_options() -> None:
    """The promoted command carries the declared positional and options."""
    command = _migrate_command(_typed_app({}))
    names = {param.name for param in command.params}
    assert "app" in names
    option_decls = {decl for param in command.params for decl in getattr(param, "opts", [])}
    assert "--fake" in option_decls
    assert "--level" in option_decls
    assert "-l" in option_decls


def test_typed_shortcut_dispatches_parsed_values() -> None:
    """Invoking the command parses positional + options into typed values."""
    captured: dict[str, object] = {}
    app = _typed_app(captured)
    result = CliRunner().invoke(app, ["migrate", "users", "--fake", "-l", "debug"])
    assert result.exit_code == 0
    assert captured == {"app": "users", "fake": True, "level": "debug"}


def test_typed_shortcut_groups_under_panel() -> None:
    """The command carries its ``group`` as the rich help panel."""
    command = _migrate_command(_typed_app({}))
    assert getattr(command, "rich_help_panel", None) == "Database"


def test_typed_shortcut_through_suppress_wrapper() -> None:
    """The signature survives the ``suppress_known_exceptions`` wrapper (root.py path).

    Mirrors ``cli/root.py:_wire_typed_shortcut`` exactly: wrap first, then set
    ``__signature__`` on the wrapper, and confirm typer still introspects it.
    """
    from cupli.utils.exceptions import suppress_known_exceptions

    captured: dict[str, object] = {}
    rows = [{"name": "app", "type": "str", "required": True}, {"name": "fake", "type": "bool"}]
    signature, annotations = build_signature(specs_from_cache(rows))

    def _runner(ctx: typer.Context, **values: object) -> None:
        _ = ctx
        captured.update(values)

    runner = suppress_known_exceptions(_runner)
    runner.__signature__ = signature  # type: ignore[attr-defined]
    runner.__annotations__ = annotations

    app = typer.Typer(add_completion=False)
    app.command(name="migrate")(runner)
    app.command(name="noop")(lambda: None)

    result = CliRunner().invoke(app, ["migrate", "users", "--fake"])
    assert result.exit_code == 0
    assert captured == {"app": "users", "fake": True}
