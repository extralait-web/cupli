"""Pre-create host placeholders for sub-mounts under bind targets.

Docker daemon (running as root) creates a missing mount point at bind time. For
a bind ``host:/app`` plus sub-mounts under ``/app`` (named volumes, cupli
mounts, additional binds), the sub-mount targets resolve to paths on the host
under ``host`` and the daemon creates them as **root** if they are missing.
Pre-creating those placeholders as the cupli user side-steps that — the daemon
finds an existing mount point and skips the root-owned creation.

The helper runs silently before compose verbs that materialise mounts (``up`` /
``build`` / ``run`` / ``watch``) and is a no-op when the resolved compose has
no sub-mounts under binds. Any failure (docker unavailable, parse error,
permission) is swallowed so a routine invocation is never blocked by prep.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cupli.utils.subprocess import run_command

if TYPE_CHECKING:
    from cupli.services.compose_service import CompiledPlan


def prepare_mount_targets(plan: CompiledPlan) -> None:
    """Pre-create host placeholders for sub-mounts under bind targets.

    Reads the resolved compose config via ``docker compose config --format
    json``, walks each service's ``volumes:``, and for every volume target that
    lies under a bind's target — creates the placeholder on the host as the
    current user. Idempotent (``exist_ok``); silent on every failure mode.
    """
    # Prep must never block compose: swallow every error class.
    try:
        config = _resolved_config(plan)
    except Exception:
        return
    if not isinstance(config, dict):
        return
    services = config.get("services") or {}
    if not isinstance(services, dict):
        return
    for svc in services.values():
        if isinstance(svc, dict):
            _prepare_service(svc)


def _resolved_config(plan: CompiledPlan) -> dict[str, Any] | None:
    """Run ``docker compose config --format json`` against the plan's env."""
    from cupli.services.compose_service import build_argv, build_env

    argv = build_argv(plan, ["config", "--format", "json"])
    env = {**os.environ, **build_env(plan)}
    completed = run_command(argv, cwd=plan.project_dir, env=env, stream=False, check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return json.loads(completed.stdout)


def _prepare_service(svc: dict[str, Any]) -> None:
    """Pre-create host paths for one service's mounts in two passes."""
    volumes = [v for v in (svc.get("volumes") or []) if isinstance(v, dict) and v.get("target")]
    binds = sorted(
        (v for v in volumes if v.get("type") == "bind" and v.get("source")),
        key=lambda volume: len(str(volume["target"])),
    )
    if not binds:
        return
    _ensure_bind_sources(binds)
    _materialise_sub_mounts(volumes, binds)


def _ensure_bind_sources(binds: list[dict[str, Any]]) -> None:
    """Create each bind's host source directory when it is missing."""
    for bind in binds:
        source = Path(bind["source"])
        if source.exists():
            continue
        source.mkdir(parents=True, exist_ok=True)


def _materialise_sub_mounts(volumes: list[dict[str, Any]], binds: list[dict[str, Any]]) -> None:
    """Create host placeholders for every volume that lies under some bind target."""
    for volume in volumes:
        target = str(volume["target"])
        ancestor = _bind_ancestor(target, binds)
        if ancestor is None:
            continue
        rel = target[len(str(ancestor["target"])) + 1 :]
        host_target = Path(ancestor["source"]) / rel
        if host_target.exists():
            continue
        if volume.get("type") == "bind" and volume.get("source") and Path(volume["source"]).is_file():
            host_target.parent.mkdir(parents=True, exist_ok=True)
            host_target.touch(exist_ok=True)
            continue
        host_target.mkdir(parents=True, exist_ok=True)


def _bind_ancestor(target: str, binds: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the longest bind whose target is a STRICT ancestor of ``target``."""
    for bind in reversed(binds):
        bind_target = str(bind["target"])
        if target.startswith(bind_target + "/"):
            return bind
    return None


__all__ = ("prepare_mount_targets",)
