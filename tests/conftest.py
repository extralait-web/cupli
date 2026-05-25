"""Shared pytest fixtures for the cupli test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

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
