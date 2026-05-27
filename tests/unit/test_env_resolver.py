"""Tests for :mod:`cupli.core.env_resolver`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cupli.core.env_resolver import (
    check_no_shadow,
    filter_process_env,
    load_env_file,
    merge_scopes,
    substitute,
)
from cupli.domain.errors import CupliError

if TYPE_CHECKING:
    from pathlib import Path


# --- substitute() ----------------------------------------------------------


def test_substitute_known_variable() -> None:
    """A ``${VAR}`` reference resolves to its scope value."""
    assert substitute("hello ${WHO}", {"WHO": "world"}) == "hello world"


def test_substitute_unknown_returns_empty_in_permissive_mode() -> None:
    """An unknown reference resolves to ``""`` when ``strict=False``."""
    assert substitute("x=${NOPE}!", {}) == "x=!"


def test_substitute_unknown_emits_warning_in_permissive_mode(capsys) -> None:
    """In permissive mode, every unknown ``${VAR}`` use site emits a warning."""
    substitute("a=${A}, b=${B}", {})
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "unknown ${A}" in output
    assert "unknown ${B}" in output


def test_substitute_unknown_no_warning_in_strict_mode(capsys) -> None:
    """Strict mode raises and does NOT emit a warning before raising."""
    with pytest.raises(CupliError):
        substitute("${NOPE}", {}, strict=True)
    captured = capsys.readouterr()
    assert "unknown" not in captured.out + captured.err


def test_substitute_unknown_raises_in_strict_mode() -> None:
    """An unknown reference raises ``E016`` when ``strict=True``."""
    with pytest.raises(CupliError) as exc_info:
        substitute("${NOPE}", {}, strict=True)
    assert exc_info.value.code == "E016"


def test_substitute_default_literal_used_when_unset() -> None:
    """``${VAR:-default}`` returns the literal default when ``VAR`` is unset."""
    assert substitute("${NOPE:-fallback}", {}) == "fallback"


def test_substitute_default_is_skipped_when_var_is_set() -> None:
    """The default is ignored when the variable is set."""
    assert substitute("${X:-fallback}", {"X": "actual"}) == "actual"


def test_substitute_chained_via_scope_value() -> None:
    """A scope value that itself contains ``${OTHER}`` expands recursively."""
    assert substitute("${FULL}", {"FULL": "${BASE}/x", "BASE": "/srv"}) == "/srv/x"


def test_substitute_does_not_recurse_into_default_with_nested_braces() -> None:
    """Nested ``${...}`` inside a default is intentionally not supported.

    The v2 plan accepts a literal default only; users requiring chaining can
    set the variable upstream via the variable scope itself.
    """
    out = substitute("${A:-literal}", {})
    assert out == "literal"


def test_substitute_detects_simple_cycle() -> None:
    """A direct cycle (A -> A) raises ``E014``."""
    with pytest.raises(CupliError) as exc_info:
        substitute("${A}", {"A": "${A}"})
    assert exc_info.value.code == "E014"


def test_substitute_detects_indirect_cycle() -> None:
    """An indirect cycle (A -> B -> A) raises ``E014``."""
    with pytest.raises(CupliError) as exc_info:
        substitute("${A}", {"A": "${B}", "B": "${A}"})
    assert exc_info.value.code == "E014"


def test_substitute_expands_bare_var() -> None:
    """Bare ``$VAR`` (no braces) is expanded like ``${VAR}``."""
    assert substitute("path=$HOME", {"HOME": "/h"}) == "path=/h"


def test_substitute_escapes_double_dollar() -> None:
    """``$$`` is an escape for a literal ``$`` and is not treated as a ref."""
    assert substitute("price=$$5", {}) == "price=$5"
    assert substitute("$$HOME", {"HOME": "/h"}) == "$HOME"


def test_substitute_bare_var_stops_at_non_word_char() -> None:
    """A bare reference ends at the first non-identifier character."""
    assert substitute("$HOME/sub", {"HOME": "/h"}) == "/h/sub"


def test_substitute_preserves_text_around_refs() -> None:
    """Non-variable text is preserved."""
    assert substitute("a${X}b${Y}c", {"X": "1", "Y": "2"}) == "a1b2c"


# --- merge_scopes() --------------------------------------------------------


def test_merge_scopes_overlay_order() -> None:
    """Later layers override earlier values."""
    result = merge_scopes([{"A": "1"}, {"A": "2", "B": "3"}])
    assert result == {"A": "2", "B": "3"}


def test_merge_scopes_substitutes_against_earlier_layers() -> None:
    """Values may reference variables accumulated in prior layers."""
    result = merge_scopes([{"BASE": "/srv"}, {"FULL": "${BASE}/x"}])
    assert result["FULL"] == "/srv/x"


def test_merge_scopes_empty() -> None:
    """An empty layer list yields an empty scope."""
    assert merge_scopes([]) == {}


# --- check_no_shadow() -----------------------------------------------------


def test_check_no_shadow_raises_on_reserved() -> None:
    """User vars overlapping a reserved name raise ``E015``."""
    with pytest.raises(CupliError) as exc_info:
        check_no_shadow({"SPACE_NAME": "x"}, ("SPACE_NAME",))
    assert exc_info.value.code == "E015"


def test_check_no_shadow_passes_on_non_reserved() -> None:
    """A non-reserved user var passes silently."""
    check_no_shadow({"MY_VAR": "x"}, ("SPACE_NAME",))


# --- load_env_file() / filter_process_env() --------------------------------


def test_load_env_file_parses_basic_dotenv(tmp_path: Path) -> None:
    """A dotenv file is parsed into a plain dict (no interpolation)."""
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\nBAZ=qux\n# comment\n", encoding="utf-8")
    assert load_env_file(env_file) == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_missing_returns_empty(tmp_path: Path) -> None:
    """A missing env file resolves to an empty dict."""
    assert load_env_file(tmp_path / "nope") == {}


def test_load_env_file_keeps_refs_raw_for_cupli_interpolation(tmp_path: Path) -> None:
    """``${VAR}`` inside an env value is kept raw (not pre-expanded by dotenv).

    python-dotenv would otherwise collapse a reference to an unknown variable
    to an empty string; cupli must own interpolation so the value resolves
    against the cupli scope in :func:`merge_scopes`.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("DB=host:${PORT}\nBARE=host:$PORT\n", encoding="utf-8")
    assert load_env_file(env_file) == {"DB": "host:${PORT}", "BARE": "host:$PORT"}


def test_env_layer_value_interpolates_against_scope(tmp_path: Path) -> None:
    """An env-file value resolves ``${VAR}`` against an earlier scope layer."""
    env_file = tmp_path / ".env"
    env_file.write_text("DB=host:${PORT}\n", encoding="utf-8")
    merged = merge_scopes([{"PORT": "5432"}, load_env_file(env_file)])
    assert merged["DB"] == "host:5432"


def test_filter_process_env_excludes_unlisted_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only keys from the allowlist appear in the filtered map."""
    monkeypatch.setenv("PATH", "/x")
    monkeypatch.setenv("SECRET", "should-not-leak")
    filtered = filter_process_env(allowlist=("PATH",))
    assert filtered == {"PATH": "/x"}


# --- property-based --------------------------------------------------------

_var_names = st.text(
    alphabet=st.characters(min_codepoint=ord("A"), max_codepoint=ord("Z")),
    min_size=1,
    max_size=4,
)
_var_values = st.text(
    alphabet=st.characters(blacklist_characters="${}", min_codepoint=32, max_codepoint=126),
    min_size=0,
    max_size=8,
)


@given(scope=st.dictionaries(_var_names, _var_values, max_size=6))
@settings(max_examples=80, suppress_health_check=(HealthCheck.too_slow,))
def test_substitute_is_idempotent_when_no_refs(scope: dict[str, str]) -> None:
    """A string without ``${...}`` references is returned unchanged."""
    for value in scope.values():
        assert substitute(value, scope) == value


@given(name=_var_names, value=_var_values)
def test_substitute_single_ref_returns_value(name: str, value: str) -> None:
    """A single ``${NAME}`` reference resolves to the mapped value."""
    assert substitute(f"<${{{name}}}>", {name: value}) == f"<{value}>"
