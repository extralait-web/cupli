"""Tests for :mod:`cupli.cli._shortcuts` run-rendering and arg parsing."""

from __future__ import annotations

import pytest

from cupli.cli._shortcuts import ArgSpec, parse_extra, render_run, specs_from_models
from cupli.domain.models import CommandShortcut


def _spec(**overrides: object) -> ArgSpec:
    base: dict[str, object] = {
        "name": "x",
        "help": None,
        "type": "str",
        "is_option": False,
        "short": None,
        "required": False,
        "default": None,
    }
    base.update(overrides)
    return ArgSpec(**base)  # type: ignore[typeddict-item]


def test_render_quotes_string_values() -> None:
    """A string value is shell-quoted so it cannot break out of the snippet."""
    specs = [_spec(name="path")]
    rendered = render_run("ls {{path}}", specs, {"path": "a b"})
    assert rendered == "ls 'a b'"


def test_render_blocks_shell_injection() -> None:
    """A malicious value stays a single quoted token (no command break-out)."""
    specs = [_spec(name="msg")]
    rendered = render_run("echo {{msg}}", specs, {"msg": "; rm -rf /"})
    assert rendered == "echo '; rm -rf /'"


def test_render_bool_flag_on_and_off() -> None:
    """A bool option expands to its flag when truthy and to empty otherwise."""
    specs = [_spec(name="fake", type="bool", is_option=True)]
    assert render_run("migrate {{fake}}", specs, {"fake": True}) == "migrate --fake"
    assert render_run("migrate {{fake}}", specs, {"fake": False}) == "migrate "


def test_render_uses_default_when_value_missing() -> None:
    """An omitted value falls back to the declared default."""
    specs = [_spec(name="path", default=".")]
    assert render_run("ls {{path}}", specs, {}) == "ls ."


def test_render_bool_uses_default_when_omitted() -> None:
    """A bool flag with a truthy default renders the flag when no value is passed."""
    specs = [_spec(name="fake", type="bool", is_option=True, default="true")]
    assert render_run("migrate {{fake}}", specs, {}) == "migrate --fake"


def test_render_repeated_placeholder_quoted_each_time() -> None:
    """Each occurrence of a placeholder is substituted and quoted independently."""
    specs = [_spec(name="x")]
    assert render_run("a {{x}} b {{x}}", specs, {"x": "v w"}) == "a 'v w' b 'v w'"


def test_render_handles_spaced_placeholder() -> None:
    """``{{ name }}`` with surrounding whitespace is substituted too."""
    specs = [_spec(name="path")]
    assert render_run("ls {{ path }}", specs, {"path": "src"}) == "ls src"


def test_parse_extra_positional_and_option() -> None:
    """``parse_extra`` parses positionals and options like the top-level form."""
    specs = [
        _spec(name="app", required=True),
        _spec(name="fake", type="bool", is_option=True),
        _spec(name="level", is_option=True, short="l", default="info"),
    ]
    values = parse_extra(specs, ["users", "--fake", "-l", "debug"])
    assert values == {"app": "users", "fake": True, "level": "debug"}


def test_parse_extra_int_coercion() -> None:
    """An ``int`` option is coerced to a Python int."""
    specs = [_spec(name="workers", type="int", is_option=True, default="4")]
    values = parse_extra(specs, ["--workers", "8"])
    assert values == {"workers": 8}


def test_specs_from_models_marks_bool_as_option() -> None:
    """A ``bool`` arg is reported as an option even without ``option: true``."""
    shortcut = CommandShortcut.model_validate(
        {"container": "api", "run": "x {{fake}}", "args": [{"name": "fake", "type": "bool"}]},
    )
    specs = specs_from_models(shortcut.args)
    assert specs[0]["is_option"] is True


def test_parse_extra_missing_required_raises() -> None:
    """A missing required positional surfaces a click usage error."""
    import click

    specs = [_spec(name="app", required=True)]
    with pytest.raises(click.UsageError):
        parse_extra(specs, [])
