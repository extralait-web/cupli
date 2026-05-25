"""Per-invocation runtime context.

A ``RuntimeContext`` is built once by the typer root callback and threaded
through the rest of the program via ``ctx.obj``. It is immutable.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from cupli.domain.enums import LogLevel


class RuntimeContext(BaseModel):
    """Immutable per-invocation context.

    Attributes:
        space_path: absolute path to the loaded space.cupli.yaml file.
        space_dir: directory containing the space file.
        state_dir: ``.locals/<space>/state/`` directory for caches and locks.
        log_level: effective log level chosen by the user (verbose/quiet flags).
        strict_vars: if True, unknown ``${VAR}`` references raise E016.
        allow_shadow: if True, user variables may shadow reserved auto-vars.
        no_color: if True, suppress ANSI colours.
        time_profile: if True, print phased timing to stderr.
        now: invocation timestamp; useful for deterministic logs in tests.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    space_path: Path
    space_dir: Path
    state_dir: Path
    log_level: LogLevel = LogLevel.WARNING
    strict_vars: bool = False
    allow_shadow: bool = False
    no_color: bool = False
    time_profile: bool = False
    now: datetime = Field(default_factory=datetime.now)
