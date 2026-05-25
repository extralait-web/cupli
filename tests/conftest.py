"""Shared pytest fixtures for the cupli test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Neutralise ANSI colouring before any cupli (and rich) modules are imported.
# CI sets ``FORCE_COLOR=1`` for human-readable build logs, which makes rich
# emit escape sequences that break substring assertions on captured stdout.
os.environ.pop("FORCE_COLOR", None)
os.environ.setdefault("NO_COLOR", "1")

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Absolute path to ``tests/fixtures``."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def spaces_dir(fixtures_dir: Path) -> Path:
    """Absolute path to ``tests/fixtures/spaces``."""
    return fixtures_dir / "spaces"


@pytest.fixture()
def tmp_space_dir(tmp_path: Path) -> Path:
    """Per-test temporary directory used as a synthetic workspace root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace
