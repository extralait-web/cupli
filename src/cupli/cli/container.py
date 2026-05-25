"""DI container carried on :attr:`typer.Context.obj`.

Each typer command pulls dependencies out of the container instead of
instantiating them inline. Services are added by later milestones — M3
ships only the runtime context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cupli.domain.runtime import RuntimeContext


@dataclass
class Container:
    """Per-invocation DI container.

    Attributes:
        runtime: immutable :class:`RuntimeContext` for this invocation.
    """

    runtime: RuntimeContext | None = None


__all__ = ("Container",)
