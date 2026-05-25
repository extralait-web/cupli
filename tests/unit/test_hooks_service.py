"""Tests for :mod:`cupli.services.hooks_service`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from cupli.core.loader import load_space
from cupli.domain.consts import HOOK_MARKER
from cupli.services.hooks_service import (
    build_shim,
    discover_targets,
    install_hooks,
    uninstall_hooks,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_repo(path: Path) -> Path:
    """Create a fake git working copy at ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


def _write_space(tmp_path: Path) -> Path:
    space_file = tmp_path / "space.cupli.yaml"
    space_file.write_text(
        "name: demo\napps:\n  api: {}\n  worker: {}\n",
        encoding="utf-8",
    )
    _make_repo(tmp_path / "src" / "apps" / "api")
    _make_repo(tmp_path / "src" / "apps" / "worker")
    return space_file


def _make_hooks_dir(tmp_path: Path) -> Path:
    hooks_dir = tmp_path / "hooks"
    (hooks_dir / "pre-commit").mkdir(parents=True)
    (hooks_dir / "pre-commit" / "01-lint.sh").write_text("#!/usr/bin/env bash\nruff check .\n")
    (hooks_dir / "pre-push").mkdir()
    (hooks_dir / "pre-push" / "01-test.sh").write_text("#!/usr/bin/env bash\npytest\n")
    return hooks_dir


def test_discover_targets_picks_apps_with_git_dir(tmp_path: Path) -> None:
    """Only apps whose path is a git working copy become targets."""
    space_file = _write_space(tmp_path)
    resolved = load_space(space_file)
    names = {target.name for target in discover_targets(resolved)}
    assert names == {"api", "worker"}


def test_build_shim_includes_marker(tmp_path: Path) -> None:
    """Generated shims carry the cupli marker on the second line."""
    space_file = _write_space(tmp_path)
    resolved = load_space(space_file)
    hooks_dir = _make_hooks_dir(tmp_path)
    target = discover_targets(resolved)[0]
    body = build_shim(target, "pre-commit", hooks_dir=hooks_dir, space_file=space_file)
    assert body.splitlines()[0] == "#!/usr/bin/env bash"
    assert HOOK_MARKER in body
    assert "command -v cupli" in body


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX executable bits are not modelled on Windows filesystems",
)
def test_install_hooks_creates_shims_with_chmod(tmp_path: Path) -> None:
    """``install_hooks`` writes executable shims under each target's .git/hooks."""
    space_file = _write_space(tmp_path)
    resolved = load_space(space_file)
    hooks_dir = _make_hooks_dir(tmp_path)
    report = install_hooks(resolved, hooks_dir)
    assert sorted(report.installed) == [
        "api:pre-commit",
        "api:pre-push",
        "worker:pre-commit",
        "worker:pre-push",
    ]
    shim = tmp_path / "src" / "apps" / "api" / ".git" / "hooks" / "pre-commit"
    assert shim.exists()
    assert HOOK_MARKER in shim.read_text()
    assert shim.stat().st_mode & 0o111  # executable bits set


def test_install_is_idempotent(tmp_path: Path) -> None:
    """Re-running ``install_hooks`` produces byte-equal shims (no churn)."""
    space_file = _write_space(tmp_path)
    resolved = load_space(space_file)
    hooks_dir = _make_hooks_dir(tmp_path)
    install_hooks(resolved, hooks_dir)
    shim = tmp_path / "src" / "apps" / "api" / ".git" / "hooks" / "pre-commit"
    before = shim.read_text(encoding="utf-8")
    install_hooks(resolved, hooks_dir)
    assert shim.read_text(encoding="utf-8") == before


def test_install_refuses_foreign_hook_without_force(tmp_path: Path) -> None:
    """A pre-existing non-cupli hook reports a conflict."""
    space_file = _write_space(tmp_path)
    resolved = load_space(space_file)
    hooks_dir = _make_hooks_dir(tmp_path)
    foreign = tmp_path / "src" / "apps" / "api" / ".git" / "hooks"
    foreign.mkdir(parents=True, exist_ok=True)
    (foreign / "pre-commit").write_text("#!/bin/bash\necho legacy\n")
    report = install_hooks(resolved, hooks_dir)
    assert any("api:pre-commit" in row for row in report.conflicts)


def test_install_detects_precommit_framework_conflict(tmp_path: Path) -> None:
    """A ``.pre-commit-config.yaml`` aborts hook install unless ``force=True``."""
    space_file = _write_space(tmp_path)
    resolved = load_space(space_file)
    hooks_dir = _make_hooks_dir(tmp_path)
    (tmp_path / "src" / "apps" / "api" / ".pre-commit-config.yaml").write_text("repos: []\n")
    report = install_hooks(resolved, hooks_dir)
    assert any(".pre-commit-config.yaml" in row for row in report.conflicts)
    assert not any(row.startswith("api:") for row in report.installed)


def test_uninstall_only_removes_cupli_hooks(tmp_path: Path) -> None:
    """User-authored hooks survive ``uninstall_hooks``."""
    space_file = _write_space(tmp_path)
    resolved = load_space(space_file)
    hooks_dir = _make_hooks_dir(tmp_path)
    install_hooks(resolved, hooks_dir)

    user_hook = tmp_path / "src" / "apps" / "worker" / ".git" / "hooks" / "pre-commit"
    user_hook.write_text("#!/bin/bash\necho mine\n")

    report = uninstall_hooks(resolved)
    assert any(row.startswith("api:") for row in report.removed)
    assert "worker:pre-commit" not in report.removed  # foreign hook untouched
    assert user_hook.exists()
    assert user_hook.read_text() == "#!/bin/bash\necho mine\n"
