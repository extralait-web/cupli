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


class DepCondition(str, Enum):
    """Compose-style start condition for a ``apps[*].deps[<name>]`` entry.

    Mirrors docker-compose ``depends_on.<svc>.condition``. When the condition is
    left unset, cupli auto-picks ``service_completed_successfully`` for a
    dependency whose ``mode: oneshot`` and ``service_started`` otherwise.
    """

    SERVICE_STARTED = "service_started"
    SERVICE_HEALTHY = "service_healthy"
    SERVICE_COMPLETED_SUCCESSFULLY = "service_completed_successfully"


class ExportStrategy(str, Enum):
    """Materialisation strategy for an ``exports[*]`` entry.

    ``BIND_SEEDED`` turns the service's ``exec_path`` into a host bind seeded
    from the image (the container then writes directly to the host — always
    live). ``SYNC`` keeps the named volume for container I/O and copies it to
    the host one-way on ``refresh_on`` events (a read-mostly mirror for IDE
    indexing).
    """

    BIND_SEEDED = "bind-seeded"
    SYNC = "sync"


class RefreshHook(str, Enum):
    """Lifecycle event after which an export is refreshed.

    Listed in ``exports[*].refresh_on``. cupli re-materialises the export for
    the affected ``from`` service after the matching operation completes.
    """

    UP = "up"
    BUILD = "build"
    RESTART = "restart"


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
