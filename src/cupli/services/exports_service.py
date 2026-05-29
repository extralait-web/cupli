"""Export materialisation (Feature ``exports:``).

Materialises a container-built directory (typically a named volume such as
``node_modules``) onto the host so IDEs that only resolve from the local
filesystem index it. Two strategies:

- ``sync`` — keep the named volume for container I/O; copy volume→host
  one-way on ``refresh_on`` events (a read-mostly mirror). Symlinks are
  preserved (``cp -a``) so pnpm's ``.pnpm`` structure stays intact.
- ``bind-seeded`` — turn the service's ``exec_path`` into a host bind seeded
  from the image, so the container writes straight to the host (always live).
  The bind itself is injected into the generated post-override; this module
  only seeds the host directory before compose starts.

Export is for IDE indexing, NOT for running host tooling — the exported tree
may carry native binaries built for the image's libc, not the host's.

cupli only touches host copies it created (tracked in ``state/exports.json``);
a foreign non-empty directory on the path surfaces as ``E032``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cupli.domain.consts import STATE_DIR
from cupli.domain.enums import ExportStrategy
from cupli.domain.errors import CupliError
from cupli.utils.console import warn
from cupli.utils.path import create_dir, read_json, write_json
from cupli.utils.subprocess import run_command

if TYPE_CHECKING:
    from cupli.core.loader import ResolvedSpace

EXPORTS_FILE = "exports.json"
"""State file recording host copies cupli materialised (``{name: {...}}``)."""

_VENV_HINTS: frozenset[str] = frozenset({".venv", "venv", "site-packages"})
"""``exec_path`` basenames that likely contain editable installs (``E034``)."""


@dataclass(frozen=True)
class ExportInfo:
    """A row returned by :func:`list_exports` for display."""

    name: str
    from_app: str
    exec_path: str
    path: Path
    strategy: str
    status: str


# --- listing ---------------------------------------------------------------


def list_exports(resolved: ResolvedSpace) -> list[ExportInfo]:
    """Build display rows for every declared export."""
    state = _read_state(resolved)
    rows: list[ExportInfo] = []
    for name, export in resolved.space.exports.items():
        path = resolved.exports[name].path
        rows.append(
            ExportInfo(
                name=name,
                from_app=export.from_app,
                exec_path=resolved.exports[name].vars["EXPORT_EXEC_PATH"],
                path=path,
                strategy=export.strategy.value,
                status=_status_of(name, path, state),
            )
        )
    return rows


def _status_of(name: str, path: Path, state: dict[str, dict]) -> str:
    """Compute the display status: missing / seeded / synced / stale."""
    entry = state.get(name)
    if entry and entry.get("status") == "stale":
        return "stale"
    if not _is_populated(path):
        return "missing"
    if entry and entry.get("status") in {"seeded", "synced"}:
        return str(entry["status"])
    return "stale"


# --- refresh / sync --------------------------------------------------------


def mark_stale(resolved: ResolvedSpace, from_app: str) -> None:
    """Flag every export of ``from_app`` as stale (called after build/up/restart).

    A subsequent :func:`sync_exports` clears the flag. Exports whose
    ``refresh_on`` includes the triggering event are synced right after, so the
    flag is transient for them; the rest stay ``stale`` until an explicit
    ``cupli exports sync``.
    """
    names = [name for name, export in resolved.space.exports.items() if export.from_app == from_app]
    if not names:
        return
    state = _read_state(resolved)
    for name in names:
        entry = state.setdefault(name, {})
        entry["status"] = "stale"
    _write_state(resolved, state)


def refresh_for_event(resolved: ResolvedSpace, from_app: str, event: str) -> list[ExportInfo]:
    """Sync every export of ``from_app`` whose ``refresh_on`` lists ``event``."""
    names = [
        name
        for name, export in resolved.space.exports.items()
        if export.from_app == from_app and event in {hook.value for hook in export.refresh_on}
    ]
    if not names:
        return []
    return sync_exports(resolved, names)


def sync_exports(
    resolved: ResolvedSpace,
    names: list[str] | None = None,
    *,
    config: dict | None = None,
) -> list[ExportInfo]:
    """Materialise / refresh the selected exports (default: all)."""
    selected = list(names) if names else list(resolved.space.exports)
    if not selected:
        return []
    state = _read_state(resolved)
    if config is None:
        config = _fetch_config(resolved, selected)
    rows = [_sync_one(resolved, name, config, state) for name in selected]
    _write_state(resolved, state)
    return rows


def _sync_one(resolved: ResolvedSpace, name: str, config: dict | None, state: dict[str, dict]) -> ExportInfo:
    """Materialise a single export and update its state entry in place."""
    export = resolved.space.exports[name]
    path = resolved.exports[name].path
    exec_path = resolved.exports[name].vars["EXPORT_EXEC_PATH"]
    _warn_editable(name, exec_path, rewrite_paths=export.rewrite_paths)
    _guard_foreign_path(name, path, state)
    if export.gitignore:
        ensure_gitignore(resolved.space_dir, [path])
    if export.strategy is ExportStrategy.BIND_SEEDED:
        status = _seed_bind(name, export.from_app, exec_path, path, config)
    else:
        status = _sync_volume(name, export.from_app, exec_path, path, config)
    state.setdefault(name, {}).update({"status": status, "path": str(path), "strategy": export.strategy.value})
    return ExportInfo(name, export.from_app, exec_path, path, export.strategy.value, status)


def clean_exports(resolved: ResolvedSpace, names: list[str] | None = None) -> list[ExportInfo]:
    """Remove host copies for ``sync`` exports; warn (keep data) for ``bind-seeded``."""
    import shutil

    selected = list(names) if names else list(resolved.space.exports)
    state = _read_state(resolved)
    rows: list[ExportInfo] = []
    for name in selected:
        export = resolved.space.exports[name]
        path = resolved.exports[name].path
        if export.strategy is ExportStrategy.BIND_SEEDED:
            warn(f"export {name!r} is bind-seeded — host data is the live bind; not removing {path}")
            status = "seeded"
        else:
            if path.exists():
                shutil.rmtree(path)
            state.pop(name, None)
            status = "missing"
        rows.append(
            ExportInfo(
                name,
                export.from_app,
                resolved.exports[name].vars["EXPORT_EXEC_PATH"],
                path,
                export.strategy.value,
                status,
            )
        )
    _write_state(resolved, state)
    return rows


# --- compose-config lookups (pure) -----------------------------------------


def service_image(config: dict | None, service_names: set[str]) -> str | None:
    """Return the resolved image of the first matching service in a compose config."""
    if config is None:
        return None
    services = config.get("services") or {}
    for svc_name, svc in services.items():
        if svc_name in service_names and isinstance(svc, dict) and svc.get("image"):
            return str(svc["image"])
    return None


def volume_for_exec_path(config: dict | None, service_names: set[str], exec_path: str) -> str | None:
    """Return the real docker volume name backing ``exec_path`` for a service.

    Resolves the service's named-volume mount at ``exec_path`` to its
    project-qualified docker volume name (from the config's top-level
    ``volumes`` map). Returns ``None`` when no named volume is mounted there.
    """
    if config is None:
        return None
    services = config.get("services") or {}
    top_volumes = config.get("volumes") or {}
    for svc_name, svc in services.items():
        if svc_name not in service_names or not isinstance(svc, dict):
            continue
        for vol in svc.get("volumes") or []:
            if isinstance(vol, dict) and vol.get("type") == "volume" and str(vol.get("target")) == exec_path:
                declared = str(vol.get("source"))
                spec = top_volumes.get(declared) or {}
                return str(spec.get("name", declared))
    return None


# --- gitignore -------------------------------------------------------------


def ensure_gitignore(space_dir: Path, paths: list[Path]) -> None:
    """Idempotently add ``paths`` to the root ``.gitignore`` under a cupli section."""
    section = "# cupli exports"
    entries = [_gitignore_entry(space_dir, path) for path in paths]
    gitignore = space_dir / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    missing = [entry for entry in entries if entry not in existing]
    if not missing:
        return
    lines = list(existing)
    if section not in lines:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(section)
    lines.extend(missing)
    gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gitignore_entry(space_dir: Path, path: Path) -> str:
    """Return the gitignore pattern for ``path`` (anchored relative when under the space)."""
    try:
        rel = path.resolve().relative_to(space_dir.resolve())
    except ValueError:
        return str(path)
    return "/" + rel.as_posix()


# --- docker materialisation ------------------------------------------------


def _seed_bind(name: str, from_app: str, exec_path: str, host_path: Path, config: dict | None) -> str:
    """Seed ``host_path`` from the service image when empty (bind-seeded strategy)."""
    if _is_populated(host_path):
        return "seeded"
    image = service_image(config, _service_names(from_app, config))
    if image is None:
        warn(f"export {name!r}: cannot seed — service image for {from_app!r} not resolved (is docker available?)")
        return "missing"
    create_dir(host_path)
    _docker_seed(image, exec_path, host_path)
    _chown_to_host(name, host_path)
    return "seeded"


def _sync_volume(name: str, from_app: str, exec_path: str, host_path: Path, config: dict | None) -> str:
    """Copy the named volume backing ``exec_path`` to ``host_path`` (sync strategy)."""
    volume = volume_for_exec_path(config, _service_names(from_app, config), exec_path)
    image = service_image(config, _service_names(from_app, config))
    if volume is None or image is None:
        warn(f"export {name!r}: cannot sync — named volume / image for {exec_path} not resolved (is docker available?)")
        return "missing"
    create_dir(host_path)
    _docker_sync(volume, image, host_path)
    _chown_to_host(name, host_path)
    return "synced"


def _docker_seed(image: str, exec_path: str, host_path: Path) -> None:
    """``docker create`` → ``docker cp`` → ``docker rm`` to seed a host directory."""
    created = run_command(["docker", "create", image], stream=False, check=False)
    cid = created.stdout.strip()
    if created.returncode != 0 or not cid:
        return
    try:
        run_command(["docker", "cp", f"{cid}:{exec_path}/.", str(host_path)], stream=False, check=False)
    finally:
        run_command(["docker", "rm", "-f", cid], stream=False, check=False)


def _docker_sync(volume: str, image: str, host_path: Path) -> None:
    """Copy a named volume to the host via a throwaway container (preserves symlinks)."""
    argv = [
        "docker",
        "run",
        "--rm",
        *_user_flag(),
        "-v",
        f"{volume}:/src:ro",
        "-v",
        f"{host_path}:/dst",
        image,
        "sh",
        "-c",
        "cp -a /src/. /dst/ 2>/dev/null || cp -a /src/. /dst/",
    ]
    run_command(argv, stream=False, check=False)


def _user_flag() -> list[str]:
    """Return ``['--user', 'uid:gid']`` on POSIX so copied files are host-owned."""
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return []
    return ["--user", f"{getuid()}:{getgid()}"]


def _chown_to_host(name: str, host_path: Path) -> None:
    """Best-effort chown of materialised files to the host user (``E033`` on failure)."""
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return
    uid, gid = getuid(), getgid()
    try:
        for entry in [host_path, *host_path.rglob("*")]:
            os.chown(entry, uid, gid, follow_symlinks=False)
    except PermissionError:
        # Files already owned by the host user (the common case) need no chown;
        # only foreign ownership trips this, which the container --user avoids.
        spec = CupliError("E033", name=name, path=str(host_path), owner=f"{uid}:{gid}")
        warn(f"{spec.args[0]}\n  {spec.hint}")


# --- guards / helpers ------------------------------------------------------


def _warn_editable(name: str, exec_path: str, *, rewrite_paths: bool) -> None:
    """Warn (``E034``) when exporting a ``.venv``-like path without ``rewrite_paths``."""
    if rewrite_paths:
        return
    if Path(exec_path).name in _VENV_HINTS:
        spec = CupliError("E034", name=name, exec_path=exec_path)
        warn(f"{spec.args[0]}\n  {spec.hint}")


def _guard_foreign_path(name: str, path: Path, state: dict[str, dict]) -> None:
    """Raise ``E032`` when ``path`` holds a non-empty dir cupli did not create."""
    if name in state:
        return
    if _is_populated(path) and not path.is_symlink():
        raise CupliError("E032", kind="export", name=name, path=str(path), what="non-empty directory")


def _is_populated(path: Path) -> bool:
    """True when ``path`` exists and is a non-empty directory."""
    if not path.exists():
        return False
    if path.is_dir():
        return any(path.iterdir())
    return True


def _service_names(from_app: str, config: dict | None) -> set[str]:
    """Service names that ``from_app`` may map to in the compose config.

    Prefers the app name itself, but also returns every service present in the
    config so a renamed compose service still resolves.
    """
    names = {from_app}
    if config:
        names |= set((config.get("services") or {}).keys())
    return names


def _fetch_config(resolved: ResolvedSpace, export_names: list[str]) -> dict | None:
    """Build a plan over the exports' ``from`` apps and read the merged compose config."""
    from cupli.services.compose_service import make_plan, resolved_compose_config

    apps = sorted({resolved.space.exports[name].from_app for name in export_names})
    try:
        plan = make_plan(resolved, services=apps)
    except Exception:
        return None
    return resolved_compose_config(plan)


def _state_path(resolved: ResolvedSpace) -> Path:
    """Return (and create) the exports state file path."""
    state_dir = Path(resolved.space_vars["LOCALS_PATH"]) / resolved.space.name / STATE_DIR
    create_dir(state_dir)
    return state_dir / EXPORTS_FILE


def _read_state(resolved: ResolvedSpace) -> dict[str, dict]:
    """Read the export state map (``{name: {...}}``)."""
    path = _state_path(resolved)
    if not path.exists():
        return {}
    raw = read_json(path)
    return {str(k): dict(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _write_state(resolved: ResolvedSpace, state: dict[str, dict]) -> None:
    """Persist the export state map (sorted)."""
    write_json(_state_path(resolved), dict(sorted(state.items())))


__all__ = (
    "EXPORTS_FILE",
    "ExportInfo",
    "clean_exports",
    "ensure_gitignore",
    "list_exports",
    "mark_stale",
    "refresh_for_event",
    "service_image",
    "sync_exports",
    "volume_for_exec_path",
)
