"""Cross-cutting domain types used between parser, services, and the CLI.

Kept in a separate module from the schema models so that:

- The CLI layer can import lightweight types without pulling in the full
  pydantic graph (faster cold start).
- ``LineMarks`` can be referenced by ``cupli.domain.exceptions`` without a
  circular import.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from cupli.domain.enums import HookKind

if TYPE_CHECKING:
    from collections.abc import Sequence


class LineMarks(BaseModel):
    """Pydantic ``loc`` tuple → (line, column) source position map.

    Built by the parser from ruamel.yaml's ``CommentedMap.lc`` data. Lookup is
    longest-prefix: ``locate(("apps", "api", "bases", 0))`` falls back to
    ``("apps", "api", "bases")`` and finally ``("apps", "api")``.

    Attributes:
        file: absolute path of the YAML file the marks were extracted from.
        items: mapping of loc-tuple → (line, column), 1-indexed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    file: Path
    items: dict[tuple[Any, ...], tuple[int, int]] = Field(default_factory=dict)

    def locate(self, loc: Sequence[Any]) -> tuple[int, int] | None:
        """Return the closest known (line, column) for a loc tuple."""
        loc_tuple = tuple(loc)
        while loc_tuple:
            mark = self.items.get(loc_tuple)
            if mark is not None:
                return mark
            loc_tuple = loc_tuple[:-1]
        return None


class HookTarget(BaseModel):
    """One discovered git-repo target for ``cupli set-hooks``.

    Attributes:
        name: logical key in the space (app/base/mount name).
        kind: which top-level section the target came from.
        repo_path: absolute host path of the git working copy.
        service: docker-compose service name to ``exec`` into.
        workdir: working directory inside the container.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: HookKind
    repo_path: Path
    service: str
    workdir: str


class ExecutionPlan(BaseModel):
    """Pre-computed compose invocation for a single lifecycle command.

    Attributes:
        services: service names in startup order (deps before dependents).
        compose_files: ``-f`` files in merge order (pre-override → user files
            → post-override).
        override_pre: optional path to the generated pre-override.
        override_post: optional path to the generated post-override.
        env_file: optional path to the generated ``--env-file``.
        project_name: ``--project-name`` value passed to docker compose.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    services: list[str] = Field(default_factory=list)
    compose_files: list[Path] = Field(default_factory=list)
    override_pre: Path | None = None
    override_post: Path | None = None
    env_file: Path | None = None
    project_name: str = ""
