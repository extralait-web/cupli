"""Project enums for the pydantic-based cupli pipeline."""

import logging
from enum import Enum, IntEnum


class LogLevel(IntEnum):
    """Log severity levels mapped onto stdlib ``logging`` integers."""

    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL
    SILENCE = logging.CRITICAL + 1


class ServiceMode(str, Enum):
    """Run mode declared on ``apps[*].mode``."""

    UP = "up"
    ONESHOT = "oneshot"
    DISABLED = "disabled"


class MountMode(str, Enum):
    """Bind-mount mode for ``mounts[*]``."""

    RW = "rw"
    RO = "ro"


class MacVolumeMode(str, Enum):
    """macOS-specific volume consistency mode for performance tuning."""

    DELEGATED = "delegated"
    CACHED = "cached"
    CONSISTENT = "consistent"


class DepMode(str, Enum):
    """Dependency mode tag on ``apps[*].deps[<svc>]``.

    A dependency starts only when the invocation's mode intersects its mode
    set. ``DEFAULT`` covers the common ``cupli start`` path.
    """

    DEFAULT = "default"
    HOOK = "hook"
    FULL = "full"


class HookKind(str, Enum):
    """Logical kind of a hook target discovered by ``set-hooks``."""

    APP = "app"
    BASE = "base"
    MOUNT = "mount"


class ExecuteMode(str, Enum):
    """Execution strategy for a multi-container ``commands[*]`` shortcut.

    ``SEQUENTIAL`` runs containers one by one and stops at the first failure
    (fail-fast). ``CONTINUE`` runs every container regardless of failures and
    reports an aggregate result. ``PARALLEL`` runs them concurrently, capturing
    each container's output to avoid interleaving.
    """

    SEQUENTIAL = "sequential"
    CONTINUE = "continue"
    PARALLEL = "parallel"
