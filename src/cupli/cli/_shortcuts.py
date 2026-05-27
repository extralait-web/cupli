"""Shared helpers for workspace-command shortcuts (``commands:``).

Centralises the logic reused by two call sites:

- ``cupli sc <name>`` (``cli/exec.py``) — parses trailing tokens against the
  command's declared ``args`` and renders the ``run`` line.
- top-level promotion (``cli/root.py``) — builds a typed CLI signature so a
  promoted command exposes its arguments/options in ``cupli <name> --help``.

Both sides operate on a normalised :class:`ArgSpec` list, produced from either
a :class:`cupli.domain.models.CommandArg` (live model) or a cache row (dict).
"""

from __future__ import annotations

import inspect
import re
import shlex
from typing import TYPE_CHECKING, Any, TypedDict

import click
import typer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from cupli.domain.models import CommandArg

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z][\w-]*)\s*\}\}")
"""Matches ``{{name}}`` placeholders inside a command's ``run`` line."""

_TRUTHY = {"1", "true", "yes", "on"}
"""String values treated as a boolean ``True`` for flag defaults."""


class ArgSpec(TypedDict):
    """Normalised declaration of one command argument.

    Attributes:
        name: identifier and ``{{name}}`` placeholder key.
        help: short description for ``--help``.
        type: ``str`` / ``int`` / ``bool``.
        is_option: True for a ``--name`` option, False for a positional.
        short: single-letter alias for an option, or None.
        required: whether the value must be supplied.
        default: value substituted when omitted (string, or None).
    """

    name: str
    help: str | None
    type: str
    is_option: bool
    short: str | None
    required: bool
    default: str | None


def specs_from_models(args: Sequence[CommandArg]) -> list[ArgSpec]:
    """Build :class:`ArgSpec` rows from live :class:`CommandArg` models."""
    return [
        ArgSpec(
            name=arg.name,
            help=arg.help,
            type=arg.type,
            is_option=arg.is_option,
            short=arg.short,
            required=arg.required,
            default=arg.default,
        )
        for arg in args
    ]


def specs_from_cache(rows: Sequence[dict[str, Any]]) -> list[ArgSpec]:
    """Build :class:`ArgSpec` rows from serialized cache dicts.

    ``is_option`` is recomputed here: a ``bool`` type is always an option even
    when the stored ``option`` flag is False.
    """
    return [_spec_from_row(row) for row in rows]


def _spec_from_row(row: dict[str, Any]) -> ArgSpec:
    """Normalise one cached arg dict into an :class:`ArgSpec`."""
    arg_type = row.get("type") or "str"
    is_option = bool(row.get("option")) or arg_type == "bool"
    return ArgSpec(
        name=row["name"],
        help=row.get("help"),
        type=arg_type,
        is_option=is_option,
        short=row.get("short"),
        required=bool(row.get("required")),
        default=row.get("default"),
    )


# --- run rendering ---------------------------------------------------------


def render_run(run: str, specs: Sequence[ArgSpec], values: Mapping[str, object]) -> str:
    """Substitute ``{{name}}`` placeholders in ``run`` with shell-safe tokens.

    String/int values are quoted via :func:`shlex.quote`; a boolean flag
    expands to its ``--name`` token when truthy and to an empty string
    otherwise. Placeholders without a matching declared arg are left intact.
    """
    by_name = {spec["name"]: spec for spec in specs}

    def _replace(match: re.Match[str]) -> str:
        spec = by_name.get(match.group(1))
        if spec is None:
            return match.group(0)
        return _render_token(spec, values.get(spec["name"]))

    return _PLACEHOLDER_RE.sub(_replace, run)


def _render_token(spec: ArgSpec, value: object) -> str:
    """Render a single placeholder substitution token."""
    if spec["type"] == "bool":
        enabled = bool(value) if value is not None else _bool_default(spec)
        return f"--{spec['name']}" if enabled else ""
    resolved = value if value is not None else spec["default"]
    if resolved is None:
        return ""
    return shlex.quote(str(resolved))


# --- parsing (cupli sc fallback) -------------------------------------------


def parse_extra(specs: Sequence[ArgSpec], extra: Sequence[str]) -> dict[str, object]:
    """Parse ``cupli sc`` trailing tokens against declared args via click.

    Builds a throwaway :class:`click.Command` from the specs so positional and
    ``--option`` parsing, defaults and required-checks match the top-level
    behaviour exactly. Raises :class:`click.UsageError` on bad input.
    """
    # The callback is never invoked: ``make_context`` only parses the tokens,
    # then the parsed values are read off the context.
    command = click.Command(name="sc", params=build_click_params(specs), callback=None)
    context = command.make_context("sc", list(extra))
    values = dict(context.params)
    _check_required(specs, values)
    return values


def _check_required(specs: Sequence[ArgSpec], values: Mapping[str, object]) -> None:
    """Raise a usage error when a required argument was not supplied.

    ``click.make_context`` parses tokens but does not enforce required values,
    so the check is explicit here to mirror the top-level command behaviour.
    """
    missing = [spec["name"] for spec in specs if spec["required"] and values.get(spec["name"]) is None]
    if missing:
        raise click.UsageError(f"missing required argument(s): {', '.join(missing)}")


def build_click_params(specs: Sequence[ArgSpec]) -> list[click.Parameter]:
    """Build click parameters (arguments + options) from arg specs."""
    params: list[click.Parameter] = []
    for spec in specs:
        if spec["is_option"]:
            params.append(_build_option(spec))
            continue
        params.append(_build_argument(spec))
    return params


def _click_type(spec: ArgSpec) -> click.ParamType:
    """Map an arg spec's declared type onto a click param type."""
    mapping: dict[str, click.ParamType] = {"int": click.INT, "bool": click.BOOL, "str": click.STRING}
    return mapping[spec["type"]]


def _build_option(spec: ArgSpec) -> click.Option:
    """Build a click ``--name`` option (or boolean flag) from a spec."""
    decls = _option_decls(spec)
    if spec["type"] == "bool":
        return click.Option(decls, is_flag=True, default=_bool_default(spec), help=spec["help"])
    return click.Option(
        decls,
        type=_click_type(spec),
        required=spec["required"],
        default=spec["default"],
        help=spec["help"],
    )


def _build_argument(spec: ArgSpec) -> click.Argument:
    """Build a positional click argument from a spec."""
    return click.Argument([spec["name"]], required=spec["required"], type=_click_type(spec), default=spec["default"])


def _option_decls(spec: ArgSpec) -> list[str]:
    """Return the option declaration strings (``--name`` plus optional ``-x``)."""
    decls = [f"--{spec['name']}"]
    if spec["short"]:
        decls.append(f"-{spec['short']}")
    return decls


def _bool_default(spec: ArgSpec) -> bool:
    """Resolve a boolean flag's default from its (string) spec default."""
    default = spec["default"]
    if default is None:
        return False
    return str(default).lower() in _TRUTHY


# --- typer signature (top-level promotion) ---------------------------------


def build_signature(specs: Sequence[ArgSpec]) -> tuple[inspect.Signature, dict[str, Any]]:
    """Build a synthetic signature + annotations for a top-level shortcut.

    The first parameter is the injected ``typer.Context``; the rest mirror the
    declared args as typed ``typer.Argument`` / ``typer.Option`` parameters.
    typer introspects the returned signature exactly as it would a hand-written
    command, so the promoted command shows real arguments/options in help.
    """
    params = [inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=typer.Context)]
    annotations: dict[str, Any] = {"ctx": typer.Context, "return": None}
    for spec in specs:
        py_type = _py_type(spec)
        params.append(
            inspect.Parameter(
                spec["name"],
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=_typer_param(spec),
                annotation=py_type,
            ),
        )
        annotations[spec["name"]] = py_type
    return inspect.Signature(params), annotations


def _py_type(spec: ArgSpec) -> type:
    """Map an arg spec's declared type onto a Python type for annotations."""
    mapping: dict[str, type] = {"int": int, "bool": bool, "str": str}
    return mapping[spec["type"]]


def _typer_param(spec: ArgSpec) -> Any:
    """Build the typer ``Argument`` / ``Option`` default for one spec."""
    if spec["is_option"]:
        return _typer_option(spec)
    return typer.Argument(_arg_default(spec), help=spec["help"])


def _typer_option(spec: ArgSpec) -> Any:
    """Build a typer ``Option`` (flag or valued) from a spec."""
    decls = _option_decls(spec)
    if spec["type"] == "bool":
        return typer.Option(_bool_default(spec), *decls, help=spec["help"])
    return typer.Option(_arg_default(spec), *decls, help=spec["help"])


def _arg_default(spec: ArgSpec) -> Any:
    """Return the typer default: Ellipsis for required, else the spec default."""
    if spec["required"]:
        return ...
    return spec["default"]


__all__ = (
    "ArgSpec",
    "build_click_params",
    "build_signature",
    "parse_extra",
    "render_run",
    "specs_from_cache",
    "specs_from_models",
)
