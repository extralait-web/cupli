"""``cupli ide setup`` — write JSON-Schema mappings for VS Code and PyCharm.

The space's YAML carries a ``# yaml-language-server: $schema=...`` directive
that handles most editors out of the box (VS Code with the YAML extension,
PyCharm 2023.2+ with the bundled YAML plugin, neovim with yaml-language-server).
This service writes explicit local config files so editors that ignore the
inline directive still get completion + validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from cupli.utils.path import create_dir, write_text

if TYPE_CHECKING:
    from pathlib import Path

IdeTarget = Literal["vscode", "pycharm", "all", "auto"]
"""Which editor configuration to write. ``"auto"`` detects from existing ``.vscode/`` / ``.idea/`` directories."""


SCHEMA_URL_DEFAULT = "https://raw.githubusercontent.com/extralait-web/cupli/main/space.schema.json"
"""Fallback location used when no local ``space.schema.json`` exists next to the workspace."""


@dataclass(frozen=True)
class IdeSetupReport:
    """Files created or updated by :func:`setup_ide`."""

    written: tuple[Path, ...] = field(default_factory=tuple)
    skipped: tuple[Path, ...] = field(default_factory=tuple)
    detected: tuple[str, ...] = field(default_factory=tuple)
    """Editors detected from existing config dirs (only set when ``target='auto'``)."""


def setup_ide(
    workspace_dir: Path,
    *,
    target: IdeTarget = "auto",
    schema_path: Path | None = None,
    force: bool = False,
) -> IdeSetupReport:
    """Write IDE schema-mapping files for the workspace.

    Args:
        workspace_dir: directory containing ``space.cupli.yaml``.
        target: which editor(s) to configure.

            * ``"auto"`` (default) — walk up from ``workspace_dir`` looking
              for ``.vscode/`` / ``.idea/`` and write only for the editors
              found at the first matching ancestor. The walk stops at the
              enclosing git-repo boundary. If nothing is detected, falls
              back to writing both (assumes a fresh workspace).
            * ``"vscode"`` — write ``.vscode/settings.json``.
            * ``"pycharm"`` — write ``.idea/jsonSchemas.xml``.
            * ``"all"`` — write both unconditionally.

        schema_path: explicit absolute path to a local ``space.schema.json``.
            Falls back to a discovery walk (workspace, repo root) or the public
            GitHub URL.
        force: overwrite existing files when True; otherwise skip them.

    Returns:
        :class:`IdeSetupReport` listing files written, skipped, and the
        editors detected (when ``target='auto'``).
    """
    schema_ref = _resolve_schema_ref(workspace_dir, schema_path)
    effective, detected = _resolve_effective_targets(workspace_dir, target)
    written: list[Path] = []
    skipped: list[Path] = []
    if "vscode" in effective:
        path = workspace_dir / ".vscode" / "settings.json"
        if _write_vscode(path, schema_ref, force):
            written.append(path)
        else:
            skipped.append(path)
    if "pycharm" in effective:
        path = workspace_dir / ".idea" / "jsonSchemas.xml"
        if _write_pycharm(path, schema_ref, force):
            written.append(path)
        else:
            skipped.append(path)
    return IdeSetupReport(written=tuple(written), skipped=tuple(skipped), detected=tuple(detected))


def _resolve_effective_targets(workspace_dir: Path, target: IdeTarget) -> tuple[set[str], list[str]]:
    """Translate ``target`` into the concrete set of editors to write for.

    Returns ``(effective, detected)`` where ``detected`` is the list of editor
    names whose config dir was found on disk (empty unless ``target='auto'``).
    """
    if target == "vscode":
        return {"vscode"}, []
    if target == "pycharm":
        return {"pycharm"}, []
    if target == "all":
        return {"vscode", "pycharm"}, []
    # auto — walk up from workspace_dir; the first ancestor with `.vscode/`
    # or `.idea/` wins. The walk stops at the enclosing git-repo boundary so
    # an unrelated IDE config further up the tree does not leak in.
    detected = _detect_editor_dirs(workspace_dir)
    if detected:
        return set(detected), detected
    # Nothing detected — write both as a safe default for a brand-new workspace.
    return {"vscode", "pycharm"}, []


_DETECT_MAX_DEPTH = 64
"""Upper bound on the parent walk depth. Paths deeper than this are pathological."""


def _detect_editor_dirs(workspace_dir: Path) -> list[str]:
    """Walk up from ``workspace_dir`` looking for ``.vscode/`` and ``.idea/``.

    Returns the editors found at the first ancestor containing any of them.
    A directory carrying ``.git`` marks the repo boundary and ends the walk.
    The walk also stops at the filesystem root and at a hard depth ceiling
    so the loop is bounded under every input.
    """
    current = workspace_dir.resolve()
    for _ in range(_DETECT_MAX_DEPTH):
        found: list[str] = []
        if (current / ".vscode").is_dir():
            found.append("vscode")
        if (current / ".idea").is_dir():
            found.append("pycharm")
        if found:
            return found
        if (current / ".git").exists():
            return []
        parent = current.parent
        if parent == current:
            return []
        current = parent
    return []


def _resolve_schema_ref(workspace_dir: Path, override: Path | None) -> str:
    """Return the schema reference to embed in the editor config.

    Order of preference: explicit ``override`` → workspace-local file →
    repo-root sibling → public GitHub URL.
    """
    if override is not None:
        return _relative_or_absolute(override, workspace_dir)
    for candidate in (workspace_dir / "space.schema.json", workspace_dir.parent / "space.schema.json"):
        if candidate.is_file():
            return _relative_or_absolute(candidate, workspace_dir)
    return SCHEMA_URL_DEFAULT


def _relative_or_absolute(path: Path, anchor: Path) -> str:
    """Return ``path`` relative to ``anchor`` when possible; absolute otherwise."""
    try:
        return f"./{path.resolve().relative_to(anchor.resolve())}"
    except ValueError:
        return str(path.resolve())


_CUPLI_YAML_GLOBS: tuple[str, ...] = (
    "*cupli*.yaml",
    "*cupli*.yml",
)
"""File-name globs that should resolve to the cupli schema.

Liberal enough to cover ``space.cupli.yaml``, ``dev.cupli.yml``,
``my-cupli-stack.yaml``, ``cupli.local.yml``, … while still excluding
unrelated YAML in the same workspace.
"""


def _write_vscode(path: Path, schema_ref: str, force: bool) -> bool:
    """Write ``.vscode/settings.json`` mapping the schema to every cupli YAML file."""
    if path.exists() and not force:
        return False
    create_dir(path.parent)
    payload = {"yaml.schemas": {schema_ref: list(_CUPLI_YAML_GLOBS)}}
    write_text(path, json.dumps(payload, indent=2) + "\n")
    return True


def _write_pycharm(path: Path, schema_ref: str, force: bool) -> bool:
    """Write ``.idea/jsonSchemas.xml`` registering the schema for cupli YAML files."""
    if path.exists() and not force:
        return False
    create_dir(path.parent)
    body = _PYCHARM_SCHEMA_XML.format(schema_ref=schema_ref, patterns=_pycharm_patterns())
    write_text(path, body)
    return True


def _pycharm_patterns() -> str:
    """Render the ``<list>`` of ``<Item pattern="true" path="..." />`` entries for PyCharm."""
    return "\n".join(
        f"                  <Item>\n"
        f'                    <option name="pattern" value="true" />\n'
        f'                    <option name="path" value="{glob}" />\n'
        f"                  </Item>"
        for glob in _CUPLI_YAML_GLOBS
    )


_PYCHARM_SCHEMA_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="JsonSchemaMappingsProjectConfiguration">
    <state>
      <map>
        <entry key="cupli space">
          <value>
            <SchemaInfo>
              <option name="name" value="cupli space" />
              <option name="relativePathToSchema" value="{schema_ref}" />
              <option name="schemaVersion" value="JSON Schema version 2020-12" />
              <option name="patterns">
                <list>
{patterns}
                </list>
              </option>
            </SchemaInfo>
          </value>
        </entry>
      </map>
    </state>
  </component>
</project>
"""


__all__ = ("IdeSetupReport", "IdeTarget", "SCHEMA_URL_DEFAULT", "setup_ide")
