"""Tests for :mod:`cupli.services.ide_setup_service`."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cupli.services.ide_setup_service import SCHEMA_URL_DEFAULT, setup_ide

if TYPE_CHECKING:
    from pathlib import Path


def test_setup_ide_writes_vscode_and_pycharm(tmp_path: Path) -> None:
    """``setup_ide(target='all')`` produces both editor config files."""
    (tmp_path / "space.schema.json").write_text("{}", encoding="utf-8")
    report = setup_ide(tmp_path, target="all")
    assert (tmp_path / ".vscode" / "settings.json").exists()
    assert (tmp_path / ".idea" / "jsonSchemas.xml").exists()
    assert len(report.written) == 2
    assert not report.skipped


def test_setup_ide_auto_writes_only_for_existing_dirs(tmp_path: Path) -> None:
    """``target='auto'`` writes only for editors whose config dir already exists."""
    (tmp_path / ".idea").mkdir()  # PyCharm-like project
    report = setup_ide(tmp_path, target="auto")
    assert (tmp_path / ".idea" / "jsonSchemas.xml").exists()
    assert not (tmp_path / ".vscode").exists()
    assert "pycharm" in report.detected
    assert "vscode" not in report.detected


def test_setup_ide_auto_writes_both_when_neither_dir_exists(tmp_path: Path) -> None:
    """A fresh workspace (no editor dirs yet) gets both configs as fallback."""
    report = setup_ide(tmp_path, target="auto")
    assert (tmp_path / ".vscode" / "settings.json").exists()
    assert (tmp_path / ".idea" / "jsonSchemas.xml").exists()
    assert report.detected == ()  # nothing was detected; both written as fallback


def test_setup_ide_auto_detects_pycharm_in_parent_dir(tmp_path: Path) -> None:
    """``target='auto'`` finds ``.idea`` in a parent dir (PyCharm-style nested workspace)."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / ".idea").mkdir()
    report = setup_ide(workspace, target="auto")
    assert (workspace / ".idea" / "jsonSchemas.xml").exists()
    assert not (workspace / ".vscode").exists()
    assert report.detected == ("pycharm",)


def test_setup_ide_auto_stops_at_git_boundary(tmp_path: Path) -> None:
    """A ``.git`` directory ends the upward walk; IDE configs above it are ignored."""
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    (tmp_path / ".idea").mkdir()
    report = setup_ide(workspace, target="auto")
    assert (workspace / ".vscode" / "settings.json").exists()
    assert (workspace / ".idea" / "jsonSchemas.xml").exists()
    assert report.detected == ()


def test_setup_ide_auto_writes_only_vscode_when_only_vscode_exists(tmp_path: Path) -> None:
    """A VS Code-only project keeps its .idea dir absent."""
    (tmp_path / ".vscode").mkdir()
    report = setup_ide(tmp_path, target="auto")
    assert (tmp_path / ".vscode" / "settings.json").exists()
    assert not (tmp_path / ".idea").exists()
    assert report.detected == ("vscode",)


def test_setup_ide_vscode_schema_mapping(tmp_path: Path) -> None:
    """The VS Code settings map the schema to every cupli yaml/yml glob."""
    (tmp_path / "space.schema.json").write_text("{}", encoding="utf-8")
    setup_ide(tmp_path, target="vscode")
    settings = json.loads((tmp_path / ".vscode" / "settings.json").read_text())
    schemas = settings["yaml.schemas"]
    schema_ref = next(iter(schemas))
    assert schema_ref.endswith("space.schema.json")
    globs = schemas[schema_ref]
    assert "*cupli*.yaml" in globs
    assert "*cupli*.yml" in globs


def test_setup_ide_falls_back_to_url_when_no_local_schema(tmp_path: Path) -> None:
    """Without a local schema file, the public GitHub URL is used."""
    report = setup_ide(tmp_path, target="vscode")
    settings = json.loads((tmp_path / ".vscode" / "settings.json").read_text())
    assert SCHEMA_URL_DEFAULT in next(iter(settings["yaml.schemas"]))
    assert len(report.written) == 1


def test_setup_ide_skips_existing_without_force(tmp_path: Path) -> None:
    """Pre-existing config files are preserved unless ``force=True``."""
    target = tmp_path / ".vscode" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"existing": true}', encoding="utf-8")
    report = setup_ide(tmp_path, target="vscode", force=False)
    assert target in report.skipped
    assert json.loads(target.read_text()) == {"existing": True}


def test_setup_ide_overwrites_with_force(tmp_path: Path) -> None:
    """``force=True`` overwrites pre-existing config files."""
    target = tmp_path / ".vscode" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"existing": true}', encoding="utf-8")
    report = setup_ide(tmp_path, target="vscode", force=True)
    assert target in report.written
    assert "yaml.schemas" in json.loads(target.read_text())


def test_setup_ide_pycharm_xml_contains_schema_ref(tmp_path: Path) -> None:
    """The PyCharm XML references the schema and matches every cupli yaml/yml glob."""
    (tmp_path / "space.schema.json").write_text("{}", encoding="utf-8")
    setup_ide(tmp_path, target="pycharm")
    body = (tmp_path / ".idea" / "jsonSchemas.xml").read_text()
    assert "JsonSchemaMappingsProjectConfiguration" in body
    assert "*cupli*.yaml" in body
    assert "*cupli*.yml" in body
    assert "space.schema.json" in body
