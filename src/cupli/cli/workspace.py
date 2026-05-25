"""CLI commands for workspace lifecycle.

Surfaces:

- ``cupli init`` — scaffold a fresh space.
- ``cupli workspace add|list|select|remove`` — registry CRUD.
- ``cupli space sync|doctor`` — work on the currently loaded space.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, cast

import typer
from rich.table import Table

from cupli.core import registry
from cupli.core.loader import load_space
from cupli.core.parser import parse_space_file
from cupli.domain.consts import DEFAULT_LOCALS_DIR, NAME_PATTERN
from cupli.domain.errors import CupliError
from cupli.services.workspace_service import (
    doctor_space,
    scaffold_space,
    sync_space,
)
from cupli.utils.console import console, error, info, success
from cupli.utils.exceptions import suppress_known_exceptions
from cupli.utils.path import create_dir

workspace_app = typer.Typer(
    name="workspace",
    help="Manage the known-spaces registry.",
    no_args_is_help=True,
)

space_app = typer.Typer(
    name="space",
    help="Operate on the currently loaded space (sync, doctor).",
    no_args_is_help=True,
)


def _complete_space_names(incomplete: str) -> list[str]:
    """Shell-completion source: registered space names matching ``incomplete``.

    Wired into every argument that accepts a registered space name so
    ``cupli workspace select <TAB>`` / ``cupli workspace remove <TAB>`` /
    ``cupli -s <TAB>`` enumerate the live registry.
    """
    try:
        known = registry.list_known_spaces()
    except CupliError:
        return []
    return [name for name in sorted(known) if name.startswith(incomplete)]


# --- top-level: init -------------------------------------------------------


@suppress_known_exceptions
def init_command(
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Name for the new space. Defaults to the target directory name."),
    ] = None,
    target: Annotated[
        Path,
        typer.Option("--path", "-p", help="Directory that will host the space."),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing space.cupli.yaml."),
    ] = False,
    no_sync: Annotated[
        bool,
        typer.Option("--no-sync", help="Skip the post-init repo sync."),
    ] = False,
    no_ide: Annotated[
        bool,
        typer.Option("--no-ide", help="Skip writing VS Code / PyCharm schema-mapping files."),
    ] = False,
) -> None:
    """Bootstrap a cupli space.

    On an empty directory: scaffold ``space.cupli.yaml`` plus the standard
    ``apps/``, ``bases/``, ``mounts/``, ``.locals/`` layout.

    On a directory that already has a ``space.cupli.yaml``: register the file
    in the registry under its declared name (NOT the directory basename),
    create any missing standard directories, and clone every declared repo
    via ``space sync``. Pass ``--force`` to overwrite the file, ``--no-sync``
    to skip the clone step.
    """
    target_resolved = target.resolve()
    existing = target_resolved / "space.cupli.yaml"

    if existing.exists() and not force:
        _ensure_existing_registered(existing)
        _ensure_standard_dirs(target_resolved)
        if not no_sync:
            _run_post_init_sync(existing)
        if not no_ide:
            _run_post_init_ide_setup(target_resolved)
        return

    effective_name = name if name is not None else _default_name_from_dir(target_resolved)
    result = scaffold_space(name=effective_name, target_dir=target_resolved, force=force)
    success(f"created {result.space_path} (name: {effective_name})")
    for one in result.created_dirs:
        info(f"  dir  {one}")
    for one in result.created_files:
        info(f"  file {one}")
    if not no_sync:
        _run_post_init_sync(result.space_path)
    if not no_ide:
        _run_post_init_ide_setup(target_resolved)


def _run_post_init_ide_setup(workspace_dir: Path) -> None:
    """Write schema-mapping files for the IDE detected around ``workspace_dir``.

    Walks up the directory tree looking for an existing ``.vscode/`` or
    ``.idea/`` (stopping at the git-repo boundary); writes only for the
    editor(s) found. On a brand-new workspace with no IDE markers anywhere
    above, writes both as a safe default.
    """
    from cupli.services.ide_setup_service import setup_ide

    report = setup_ide(workspace_dir, target="auto", force=False)
    for path in report.written:
        info(f"  ide  {path}")


def _ensure_existing_registered(space_file: Path) -> None:
    """Register a pre-existing space file under its declared name."""
    model, _ = parse_space_file(space_file)
    declared = model.name
    known = registry.list_known_spaces()
    current = known.get(declared)
    if current == space_file:
        success(f"{declared} already registered at {space_file}.")
        return
    if current is not None:
        raise CupliError("E019", name=declared, path=str(current))
    registry.add_space(declared, space_file)
    success(f"registered existing space {declared} at {space_file}.")


def _ensure_standard_dirs(target: Path) -> None:
    """Ensure the per-space state directory exists.

    ``src/apps`` / ``src/bases`` / ``src/mounts`` are created lazily by
    ``space sync`` (and by other use-cases) only when a declared component
    actually needs them — keeping the workspace footprint minimal.
    """
    path = target / DEFAULT_LOCALS_DIR
    if not path.exists():
        create_dir(path)
        info(f"  dir  {path}")


def _run_post_init_sync(space_file: Path) -> None:
    """Run ``space sync`` after init; report cloned / skipped / failed."""
    resolved = load_space(space_file)
    report = sync_space(resolved)
    if report.cloned:
        success(f"cloned: {', '.join(report.cloned)}")
    if report.skipped:
        info(f"already cloned: {', '.join(report.skipped)}")
    for failed_name, message in report.failed:
        error(f"clone failed: {failed_name}: {message}")


def _default_name_from_dir(target: Path) -> str:
    """Derive a space name from ``target.name``.

    Replaces invalid characters with hyphens, collapses runs of hyphens,
    strips edge separators. Raises ``E009`` when nothing usable remains.
    """
    raw = target.name or ""
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "-", raw)
    candidate = re.sub(r"-+", "-", candidate).strip("-_")
    if candidate and NAME_PATTERN.match(candidate):
        return candidate
    raise CupliError("E009", name=raw or str(target), pattern=NAME_PATTERN.pattern)


# --- workspace add/list/select/remove --------------------------------------


@workspace_app.command(name="add")
@suppress_known_exceptions
def workspace_add(
    name: Annotated[str, typer.Option("--name", "-n", help="Registry name.")],
    space_file: Annotated[Path, typer.Option("--file", "-f", help="Space yaml path.")],
) -> None:
    """Register an existing ``space.cupli.yaml`` under a name."""
    registry.add_space(name, space_file.resolve())
    success(f"registered {name} -> {space_file.resolve()}")


@workspace_app.command(name="list")
@suppress_known_exceptions
def workspace_list() -> None:
    """Show every registered space; the active selection is marked with ``*``."""
    known = registry.list_known_spaces()
    active = registry.get_active_space()
    if not known:
        info("no registered spaces; create one with `cupli init` or `cupli workspace add`.")
        return
    table = Table(title="Registered spaces", show_lines=False, expand=False)
    table.add_column("", style="bold yellow", width=1)
    table.add_column("name", style="cyan", no_wrap=True)
    table.add_column("path", style="white")
    table.add_column("status", style="white")
    for entry_name, entry_path in sorted(known.items()):
        status = "[green]ok[/green]" if entry_path.exists() else "[red]missing[/red]"
        marker = "*" if entry_name == active else " "
        table.add_row(marker, entry_name, str(entry_path), status)
    console.print(table)
    if active is None:
        info("no active workspace selected; use `cupli workspace select <name>`.")


@workspace_app.command(name="select")
@suppress_known_exceptions
def workspace_select(
    name: Annotated[
        str | None,
        typer.Argument(
            help="Registered space name. Omit to show the current selection.",
            autocompletion=_complete_space_names,
        ),
    ] = None,
    clear: Annotated[bool, typer.Option("--clear", help="Clear the active selection.")] = False,
) -> None:
    """Set, clear, or print the persistent active workspace.

    The active workspace is used by every cupli command when ``cwd`` is not
    inside a registered space and no ``-s``/``-f`` flag overrides it.
    """
    if clear:
        registry.set_active_space(None)
        success("active workspace cleared (cwd auto-detect only).")
        return
    if name is None:
        active = registry.get_active_space()
        if active is None:
            info("no active workspace; pass a name to select one or `--clear` to confirm.")
            return
        path = registry.get_space_path(active)
        success(f"active: {active} -> {path}")
        return
    path = registry.get_space_path(name)
    registry.set_active_space(name)
    success(f"selected {name} -> {path}")


@workspace_app.command(name="unselect")
@suppress_known_exceptions
def workspace_unselect() -> None:
    """Clear the sticky active selection so cwd-based detection resumes.

    After this, cupli falls back to:

    1. The registered space whose root is the longest prefix of ``cwd``.
    2. A ``*.cupli.ya?ml`` file scanned directly from ``cwd``.

    Equivalent to ``cupli workspace select --clear``.
    """
    previous = registry.get_active_space()
    registry.set_active_space(None)
    if previous is None:
        info("no active workspace was set; cwd auto-detect already in effect.")
        return
    success(f"unselected {previous}; cwd auto-detect resumed.")


@workspace_app.command(name="current")
@suppress_known_exceptions
def workspace_current() -> None:
    """Print the workspace that cupli would target right now."""
    detected = _detect_effective()
    if detected.is_known and detected.name == registry.get_active_space():
        success(f"current: {detected.name} -> {detected.path} (active selection)")
        return
    if detected.is_known:
        success(f"current: {detected.name} -> {detected.path} (matched by cwd)")
        return
    info(f"current: (unregistered) {detected.path} (scanned from cwd)")


@workspace_app.command(name="remove")
@suppress_known_exceptions
def workspace_remove(
    name: Annotated[
        str,
        typer.Argument(help="Registered space name.", autocompletion=_complete_space_names),
    ],
) -> None:
    """Drop a name from the registry (does not touch the filesystem)."""
    registry.remove_space(name)
    success(f"unregistered {name}")


# --- space sync/doctor -----------------------------------------------------


@space_app.command(name="sync")
@suppress_known_exceptions
def space_sync(
    ctx: typer.Context,
    apps_only: Annotated[bool, typer.Option("--apps", help="Sync only apps.")] = False,
    bases_only: Annotated[bool, typer.Option("--bases", help="Sync only bases.")] = False,
    mounts_only: Annotated[bool, typer.Option("--mounts", help="Sync only mounts.")] = False,
    workers: Annotated[int, typer.Option("--workers", "-j", help="Max concurrent operations.")] = 4,
    pull: Annotated[bool, typer.Option("--pull", help="Also `git pull` every already-cloned repo.")] = False,
) -> None:
    """Clone every missing repo, in parallel. ``--pull`` also fast-forwards existing repos."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    sections = _selected_sections(apps_only, bases_only, mounts_only)
    report = sync_space(resolved, workers=workers, **sections)
    if report.cloned:
        success(f"cloned: {', '.join(report.cloned)}")
    if report.skipped:
        info(f"already cloned: {', '.join(report.skipped)}")
    if report.failed:
        for entry_name, message in report.failed:
            error(f"{entry_name}: {message}")
        raise typer.Exit(code=1)
    if pull:
        from cupli.cli.git import _render_rows
        from cupli.services import git_service

        rows = git_service.pull(resolved, workers=workers)
        _render_rows("Git pull", rows)


@space_app.command(name="doctor")
@suppress_known_exceptions
def space_doctor(
    ctx: typer.Context,
    strict: Annotated[bool, typer.Option("--strict", help="Non-zero exit on any warning.")] = False,
) -> None:
    """Validate the current space and report missing repos / paths."""
    space_path = _resolve_space_path(ctx)
    resolved = load_space(space_path, strict_vars=_strict_vars(ctx))
    report = doctor_space(resolved)

    for row in report.ok:
        success(row)
    for row in report.warnings:
        info(f"[yellow]warn:[/yellow] {row}")
    for row in report.errors:
        error(row)

    if report.errors or (strict and report.warnings):
        raise typer.Exit(code=1)


ide_app = typer.Typer(
    name="ide",
    help="Editor integration: register the cupli JSON schema with VS Code / PyCharm.",
    no_args_is_help=True,
)


@ide_app.command(name="setup")
@suppress_known_exceptions
def ide_setup_command(
    ctx: typer.Context,
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Which editor to configure: auto | vscode | pycharm | all. "
            "`auto` walks up looking for .vscode / .idea (stops at git-repo boundary); "
            "writes both on a fresh workspace.",
        ),
    ] = "auto",
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing editor config files."),
    ] = False,
) -> None:
    """Write VS Code and / or PyCharm schema-mapping files for this workspace.

    By default walks up from the workspace looking for an existing ``.vscode``
    or ``.idea`` directory (stopping at the enclosing git-repo boundary) and
    writes only for the editors found at the first matching ancestor. On a
    brand-new workspace where nothing is detected, writes both so whichever
    editor the user opens picks up the schema. Override with explicit
    ``--target``.
    """
    from cupli.services.ide_setup_service import IdeTarget, setup_ide

    if target not in ("auto", "vscode", "pycharm", "all"):
        raise CupliError("E020", name=f"--target must be auto | vscode | pycharm | all, got {target!r}")
    space_path = _resolve_space_path(ctx)
    workspace_dir = space_path.parent.resolve()
    report = setup_ide(workspace_dir, target=cast("IdeTarget", target), force=force)
    if report.detected:
        info(f"detected: {', '.join(report.detected)}")
    for path in report.written:
        success(f"wrote {path}")
    for path in report.skipped:
        info(f"kept existing {path} (pass --force to overwrite)")
    if not report.written and not report.skipped:
        info("nothing to do — no targets selected.")


# --- helpers ---------------------------------------------------------------


def _resolve_space_path(ctx: typer.Context) -> Path:
    """Pick the space file from --space / --file / cwd auto-detect / active."""
    space_name = ctx.meta.get("space_name")
    space_file = ctx.meta.get("space_file")
    if space_file is not None:
        return space_file.resolve()
    if space_name:
        return registry.get_space_path(space_name)
    return _detect_effective().path


def _detect_effective() -> registry.DetectedSpace:
    """Detect the effective space for the current invocation.

    Same as :func:`registry.detect_current_space`, which itself falls back to
    the persistent active selection when the cwd is not inside any registered
    space and no fresh ``space.cupli.yaml`` is found.
    """
    return registry.detect_current_space(Path.cwd())


def _strict_vars(ctx: typer.Context) -> bool:
    """Read the ``--strict-vars`` flag stashed by the root callback."""
    return bool(ctx.meta.get("strict_vars", False))


def _selected_sections(
    apps_only: bool,
    bases_only: bool,
    mounts_only: bool,
) -> dict[str, bool]:
    """Return include_* kwargs for :func:`sync_space` based on CLI flags."""
    no_filter = not (apps_only or bases_only or mounts_only)
    return {
        "include_apps": no_filter or apps_only,
        "include_bases": no_filter or bases_only,
        "include_mounts": no_filter or mounts_only,
    }


__all__ = ("init_command", "space_app", "workspace_app")
