"""C3 linearisation for ``apps[*].bases`` multi-inheritance.

In v1 the schema keeps bases flat (a ``BaseAppModel`` has no nested ``bases``
field). The general C3 algorithm is still in place so that future schemas can
nest bases without rewriting the resolution step.

The merge step follows the canonical C3 description: at each iteration, pick
the first head that does not appear in the tail of any remaining sequence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cupli.domain.errors import CupliError

if TYPE_CHECKING:
    from cupli.domain.models import SpaceModel


def c3_linearise(space: SpaceModel, app_name: str) -> list[str]:
    """Return base names of ``app_name`` in C3 merge order.

    Earlier names in the returned list override later ones — i.e. when two
    bases declare the same variable, the first wins.

    Args:
        space: validated space model.
        app_name: key of ``space.apps``.

    Returns:
        Ordered list of base names. Empty when the app has no bases.

    Raises:
        CupliError: ``E010`` when ``app_name`` is not in ``space.apps``;
            ``E011`` when no consistent linearisation exists (impossible with
            flat bases but possible once nested bases are supported).
    """
    if app_name not in space.apps:
        raise CupliError("E010", app=app_name)

    direct_bases = list(space.apps[app_name].bases)
    if not direct_bases:
        return []

    sequences = [_linearisation_of(space, base) for base in direct_bases]
    sequences.append(direct_bases.copy())
    return _merge(sequences)


def _linearisation_of(space: SpaceModel, base_name: str) -> list[str]:
    """Return the linearisation of a single base.

    With flat bases this is just ``[base_name]``. When the schema gains a
    ``bases[<n>].bases`` field, this function should recurse:

        parents = space.bases[base_name].bases
        sequences = [_linearisation_of(space, p) for p in parents]
        sequences.append(parents)
        return [base_name, *_merge(sequences)]
    """
    _ = space  # reserved for the future nested-bases recursion
    return [base_name]


def _merge(sequences: list[list[str]]) -> list[str]:
    """C3 merge step.

    Args:
        sequences: list of non-empty lists. Mutated in place.

    Returns:
        Merged linearisation.

    Raises:
        CupliError: ``E011`` when no consistent merge exists.
    """
    result: list[str] = []
    pending = [seq[:] for seq in sequences if seq]

    while pending:
        candidate = _next_candidate(pending)
        if candidate is None:
            raise CupliError("E011", sequences=repr(pending))
        result.append(candidate)
        pending = _drop_candidate(pending, candidate)

    return result


def _next_candidate(sequences: list[list[str]]) -> str | None:
    """Return the first head that does not appear in any tail."""
    for seq in sequences:
        head = seq[0]
        if not _head_in_any_tail(head, sequences):
            return head
    return None


def _head_in_any_tail(head: str, sequences: list[list[str]]) -> bool:
    """Return True when ``head`` appears in the tail (index>=1) of any sequence."""
    return any(head in other[1:] for other in sequences)


def _drop_candidate(sequences: list[list[str]], candidate: str) -> list[list[str]]:
    """Remove ``candidate`` from the head of any sequence; drop emptied sequences."""
    remaining: list[list[str]] = []
    for seq in sequences:
        if seq and seq[0] == candidate:
            seq = seq[1:]
        if seq:
            remaining.append(seq)
    return remaining


__all__ = ("c3_linearise",)
