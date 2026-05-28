"""Tests for :mod:`cupli.cli.root` driven via :class:`typer.testing.CliRunner`."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cupli.cli.root import app


@pytest.fixture()
def runner() -> CliRunner:
    """Provide a fresh CliRunner per test."""
    return CliRunner()


def test_help_exits_clean(runner: CliRunner) -> None:
    """``cupli --help`` exits 0 with the cupli banner."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Cupli" in result.stdout


def test_version_flag(runner: CliRunner) -> None:
    """``cupli --version`` prints version info and exits 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "cupli version" in result.stdout


def test_version_subcommand(runner: CliRunner) -> None:
    """``cupli version`` mirrors the ``--version`` flag."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "cupli version" in result.stdout


def test_short_version_flag(runner: CliRunner) -> None:
    """``cupli -V`` prints the bare ``cupli <version>`` line for shell scripts."""
    from cupli.version import VERSION

    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    output = result.stdout.strip()
    assert output == f"cupli {VERSION}"


def test_list_flag(runner: CliRunner) -> None:
    """``cupli --list`` shows the command table."""
    result = runner.invoke(app, ["--list"])
    assert result.exit_code == 0
    assert "version" in result.stdout
    assert "explain" in result.stdout


def test_click_group_commands_duck_typing() -> None:
    """The group-commands helper accepts any object exposing a ``commands`` dict.

    typer ≥0.25 / click ≥8.4 changed the class hierarchy so ``TyperGroup`` no
    longer ``isinstance(_, click.Group)``; the helper must duck-type to keep
    ``cupli --list`` working on both lines.
    """
    from cupli.cli.root import _click_group_commands

    class _GroupLike:
        commands: dict[str, object] = {"up": object(), "down": object()}

    class _NotGroup:
        not_commands = {}

    assert _click_group_commands(_GroupLike()) == {"up": _GroupLike.commands["up"], "down": _GroupLike.commands["down"]}
    assert _click_group_commands(_NotGroup()) is None
    assert _click_group_commands(object()) is None


def test_explain_known_code(runner: CliRunner) -> None:
    """``cupli explain E001`` prints the catalog entry."""
    result = runner.invoke(app, ["explain", "E001"])
    assert result.exit_code == 0
    assert "E001" in result.stdout
    assert "Space file not found" in result.stdout


def test_explain_unknown_code_falls_back_to_e028(runner: CliRunner) -> None:
    """``cupli explain E999`` resolves to the E028 fallback message."""
    result = runner.invoke(app, ["explain", "E999"])
    assert result.exit_code == 0
    assert "E999" in result.stdout


def test_explain_list_all(runner: CliRunner) -> None:
    """``cupli explain --list`` enumerates every known code."""
    result = runner.invoke(app, ["explain", "--list"])
    assert result.exit_code == 0
    assert "E001" in result.stdout
    assert "E028" in result.stdout


def test_no_args_prints_help(runner: CliRunner) -> None:
    """Running ``cupli`` with no arguments shows help and exits non-zero."""
    result = runner.invoke(app, [])
    assert "Cupli" in result.stdout
