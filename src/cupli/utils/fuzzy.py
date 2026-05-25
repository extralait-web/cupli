"""Fuzzy matching for CLI typo suggestions.

Used when ``cupli <unknown>`` is invoked — we compute the closest candidate
names from the registered command set and surface a "did you mean" hint
instead of silently routing to ``exec`` (the elc footgun we explicitly
reject in v2 plan §0).
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def suggest(
    name: str,
    candidates: Iterable[str],
    *,
    n: int = 3,
    cutoff: float = 0.6,
) -> list[str]:
    """Return up to ``n`` candidates similar to ``name``.

    Args:
        name: the misspelled token.
        candidates: pool of valid names to compare against.
        n: maximum number of suggestions.
        cutoff: similarity threshold (0..1) passed to ``difflib``.

    Returns:
        Ordered list of best matches; empty when nothing crosses ``cutoff``.
    """
    return difflib.get_close_matches(name, list(candidates), n=n, cutoff=cutoff)


__all__ = ("suggest",)
