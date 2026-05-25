"""Tests for ``cupli git status / pull / fetch / checkout``."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cupli.cli.git import _parse_map
from cupli.cli.root import app
from cupli.core import registry
from cupli.domain.errors import CupliError
from cupli.services import git_service


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the registry to a per-test file."""
    registry_path = tmp_path / "spaces.json"
    monkeypatch.setattr(registry, "spaces_registry_path", lambda: registry_path)
    return registry_path


@pytest.fixture()
def runner() -> CliRunner:
    """Fresh ``CliRunner`` per test."""
    return CliRunner()


def _space(tmp_path: Path) -> Path:
    space = tmp_path / "space.cupli.yaml"
    space.write_text(
        "name: demo\napps:\n  api:\n    service:\n      image: alpine:3.20\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "apps" / "api" / ".git").mkdir(parents=True)
    return space


def _row(*, name: str = "api", state: str = "clean") -> git_service.GitRow:
    return git_service.GitRow(
        name=name,
        kind="app",
        path=Path("/tmp") / name,
        branch="main",
        state=state,
        detail="",
    )


def test_parse_map_returns_empty_for_none() -> None:
    """An absent ``--map`` set produces an empty dict."""
    assert _parse_map(None) == {}


def test_parse_map_parses_repeats() -> None:
    """Each ``name=branch`` item lands as a separate key."""
    assert _parse_map(["api=feature/x", "web=main"]) == {"api": "feature/x", "web": "main"}


def test_parse_map_rejects_missing_equals() -> None:
    """Entries without ``=`` raise ``CupliError E020``."""
    with pytest.raises(CupliError) as exc_info:
        _parse_map(["api"])
    assert exc_info.value.code == "E020"


def test_parse_map_rejects_empty_sides() -> None:
    """Empty name or branch raises ``CupliError E020``."""
    with pytest.raises(CupliError) as exc_info:
        _parse_map(["=main"])
    assert exc_info.value.code == "E020"


def test_status_command_renders_rows(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cupli git status`` invokes ``git_service.status`` and prints the table."""
    _ = isolated_registry
    space = _space(tmp_path)
    captured: list[object] = []

    def _fake_status(_resolved: object, *, selectors: object, workers: int) -> list[git_service.GitRow]:
        captured.append((selectors, workers))
        return [_row()]

    monkeypatch.setattr(git_service, "status", _fake_status)
    result = runner.invoke(app, ["-f", str(space), "git", "status"])
    assert result.exit_code == 0, result.stdout
    assert captured == [(None, 4)]


def test_pull_command_exits_non_zero_on_error_row(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error row makes ``git pull`` exit with code 1."""
    _ = isolated_registry
    space = _space(tmp_path)

    def _fake_pull(*_args: object, **_kwargs: object) -> list[git_service.GitRow]:
        return [_row(state="error")]

    monkeypatch.setattr(git_service, "pull", _fake_pull)
    result = runner.invoke(app, ["-f", str(space), "git", "pull"])
    assert result.exit_code == 1


def test_pull_command_passes_rebase_flag(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--rebase`` propagates into the service call."""
    _ = isolated_registry
    space = _space(tmp_path)
    captured: dict[str, object] = {}

    def _fake_pull(_resolved: object, *, selectors: object, rebase: bool, workers: int) -> list[git_service.GitRow]:
        captured.update({"selectors": selectors, "rebase": rebase, "workers": workers})
        return [_row()]

    monkeypatch.setattr(git_service, "pull", _fake_pull)
    runner.invoke(app, ["-f", str(space), "git", "pull", "--rebase"])
    assert captured["rebase"] is True


def test_fetch_command_propagates_workers(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``-j 2`` propagates into the service call."""
    _ = isolated_registry
    space = _space(tmp_path)
    captured: dict[str, object] = {}

    def _fake_fetch(_resolved: object, *, selectors: object, workers: int) -> list[git_service.GitRow]:
        captured.update({"workers": workers, "selectors": selectors})
        return [_row()]

    monkeypatch.setattr(git_service, "fetch", _fake_fetch)
    runner.invoke(app, ["-f", str(space), "git", "fetch", "-j", "2"])
    assert captured["workers"] == 2


def test_checkout_command_passes_branch_and_overrides(
    runner: CliRunner,
    tmp_path: Path,
    isolated_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default branch + per-repo overrides reach the service."""
    _ = isolated_registry
    space = _space(tmp_path)
    captured: dict[str, object] = {}

    def _fake_checkout(
        _resolved: object,
        branch: str | None,
        *,
        selectors: object,
        overrides: dict[str, str],
        workers: int,
    ) -> list[git_service.GitRow]:
        captured.update(
            {"branch": branch, "selectors": selectors, "overrides": overrides, "workers": workers},
        )
        return [_row()]

    monkeypatch.setattr(git_service, "checkout", _fake_checkout)
    result = runner.invoke(
        app,
        ["-f", str(space), "git", "checkout", "main", "-m", "api=feature/x"],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["branch"] == "main"
    assert captured["overrides"] == {"api": "feature/x"}
