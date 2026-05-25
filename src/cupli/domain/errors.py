"""Numbered cupli error catalog plus the structured ``CupliError`` exception.

Layout:

- ``ERRORS`` — code → spec (title/template/hint) catalogue.
- ``error_message`` / ``error_spec`` / ``explain`` — formatting helpers.
- ``CupliError`` — structured exception carrying a catalogue code.
- ``ValidationFailure`` — specialised ``CupliError`` wrapping
  ``pydantic.ValidationError`` with file + line/column context.

The catalogue + exception classes live together because they are tightly
coupled: every ``CupliError`` instance dispatches to an ``ERRORS`` entry to
fetch its title and hint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from cupli.domain.plan import LineMarks


class ErrorSpec(TypedDict):
    """Structured row of the error catalog."""

    title: str
    template: str
    hint: str


ERRORS: Final[dict[str, ErrorSpec]] = {
    "E001": ErrorSpec(
        title="Space file not found",
        template="Cupli space file not found at {path}",
        hint="Run `cupli init` to scaffold a workspace, or pass --file <path>.",
    ),
    "E002": ErrorSpec(
        title="Validation failed",
        template="Failed to validate {file}: {count} error(s)",
        hint="Fix the fields listed above (each entry includes file:line:col when known).",
    ),
    "E003": ErrorSpec(
        title="Empty space file",
        template="Space file {path} is empty or contains only comments",
        hint="Add the required `name:` and `apps:` keys, or re-scaffold with `cupli init`.",
    ),
    "E004": ErrorSpec(
        title="YAML parse error",
        template="Failed to parse YAML at {path}:{line}:{col} — {message}",
        hint="Fix the YAML syntax; cupli expects YAML 1.2.",
    ),
    "E005": ErrorSpec(
        title="Unknown base",
        template="App '{app}' references base '{base}', which is not declared in `bases:`",
        hint="Declare the base under top-level `bases:`, or fix the typo.",
    ),
    "E006": ErrorSpec(
        title="Unknown dep",
        template="App '{app}' references dep '{dep}', which is not declared in `apps:`",
        hint="Declare the dependency under top-level `apps:`, or remove the dep.",
    ),
    "E007": ErrorSpec(
        title="Unsupported schema version",
        template="schema_version {value} is not supported by this cupli (only 1 is supported)",
        hint="Run `cupli upgrade-config`, or pin to a matching cupli version.",
    ),
    "E008": ErrorSpec(
        title="Cupli version mismatch",
        template="Space requires cupli {required}, but {actual} is installed",
        hint="Upgrade cupli, or relax cupli_min/cupli_max in space.cupli.yaml.",
    ),
    "E009": ErrorSpec(
        title="Invalid name",
        template="Name '{name}' does not match {pattern}",
        hint="Use letters, digits, hyphens, and underscores; start with a letter.",
    ),
    "E010": ErrorSpec(
        title="Unknown app for C3 linearisation",
        template="App '{app}' is not declared",
        hint="Internal: c3_linearise() was called with an unknown app name.",
    ),
    "E011": ErrorSpec(
        title="Cannot linearise bases",
        template="No consistent C3 linearisation for: {sequences}",
        hint="Two bases declare conflicting orderings; reorder `apps[*].bases`.",
    ),
    "E012": ErrorSpec(
        title="Unknown hosted_in",
        template="Mount '{mount}' references hosted_in '{host}', which is not declared in `apps:`",
        hint="Declare the host app, or fix the typo.",
    ),
    "E013": ErrorSpec(
        title="Mount exec_path not absolute",
        template="Mount '{mount}' has exec_path '{value}', which must be an absolute POSIX path",
        hint="Use a path starting with `/`; ${{VAR}} references are also accepted.",
    ),
    "E014": ErrorSpec(
        title="Variable cycle",
        template="Variable cycle detected: {chain}",
        hint="Break the cycle by removing or rewriting one of the variable references.",
    ),
    "E015": ErrorSpec(
        title="Reserved variable shadowed",
        template="User variable '{name}' shadows a reserved auto-variable",
        hint="Rename the variable, or pass --allow-shadow.",
    ),
    "E016": ErrorSpec(
        title="Unknown variable",
        template="Variable '${{ {name} }}' is referenced but not defined",
        hint="Declare the variable, or drop --strict-vars.",
    ),
    "E017": ErrorSpec(
        title="Repo clone failed",
        template="`git clone {repo}` into {dest} failed with exit code {exit_code}",
        hint="Check git access; ensure SSH agent is running for SSH URLs.",
    ),
    "E018": ErrorSpec(
        title="post_clone failed",
        template="post_clone for '{target}' failed with exit code {exit_code}",
        hint="Review the post_clone command output above.",
    ),
    "E019": ErrorSpec(
        title="Space already registered",
        template="Space '{name}' is already registered at {path}",
        hint="Use a different name, or `cupli workspace remove <name>` first.",
    ),
    "E020": ErrorSpec(
        title="Space not registered",
        template="Space '{name}' is not in the registry",
        hint="Run `cupli workspace list` to see known spaces.",
    ),
    "E021": ErrorSpec(
        title="extends chain too deep",
        template="space.extends chains exceed depth 1 (v1 limit)",
        hint="Flatten the extends chain; multi-level support is planned for a future release.",
    ),
    "E022": ErrorSpec(
        title="Workspace command shadows builtin",
        template="Workspace command '{name}' conflicts with a built-in cupli command",
        hint="Rename the command in `commands:`.",
    ),
    "E023": ErrorSpec(
        title="Hook target not a git repo",
        template="Cannot install hooks in '{target}' — not a git working copy",
        hint="Clone the target first via `cupli space sync`.",
    ),
    "E024": ErrorSpec(
        title="Hook conflict",
        template="Hook {hook} in {target} was authored by another tool",
        hint="Pass --force to overwrite, or --backup to keep a copy first.",
    ),
    "E025": ErrorSpec(
        title="Docker daemon unreachable",
        template="`docker info` failed: {message}",
        hint="Start Docker Desktop or the docker daemon, then retry.",
    ),
    "E026": ErrorSpec(
        title="docker compose v2 required",
        template="Detected docker compose {version}; cupli requires {required} or newer",
        hint="Upgrade Docker Compose to v2.20 or newer.",
    ),
    "E027": ErrorSpec(
        title="Lock contention",
        template="Workspace '{name}' is locked by pid {pid}",
        hint="Wait for the other invocation, or run `cupli space doctor --strict` to clear stale locks.",
    ),
    "E028": ErrorSpec(
        title="Unknown error code",
        template="No such cupli error code: {unknown_code}",
        hint="Run `cupli explain --list` to see all codes.",
    ),
    "E029": ErrorSpec(
        title="Space file already exists",
        template="A space file already exists at {path}",
        hint="Pass --force to overwrite, or run `cupli init` in a different directory.",
    ),
    "E030": ErrorSpec(
        title="Env-var name collision",
        template="Per-component env var {var} would be produced by multiple components: {names}",
        hint=(
            "Rename one of the components so their upper-cased, dash-to-underscore"
            " forms differ (e.g. `shop-api` and `shop_api` both yield `SHOP_API`)."
        ),
    ),
    "E031": ErrorSpec(
        title="Service not declared in any compose source",
        template=(
            "App {app} drives service {service!r}, but no compose-fragment or"
            " inline override declares it (missing: {missing})."
        ),
        hint=(
            "Either declare the service in a compose-fragment listed under"
            " `composes:` (and run `cupli space sync` if the repo is not cloned"
            " yet), or define it inline under `service:` / `services:` with at"
            " least one compose-spec field (e.g. `image:`)."
        ),
    ),
}
"""Catalog of all numbered cupli errors."""


def error_spec(code: str) -> ErrorSpec:
    """Return the catalog entry for ``code`` or the ``E028`` fallback."""
    spec = ERRORS.get(code)
    if spec is not None:
        return spec
    return ERRORS["E028"]


def error_message(code: str, **fmt: object) -> str:
    """Format the catalog message template for ``code`` with ``fmt`` kwargs.

    Unknown codes resolve to the ``E028`` template formatted with ``code``.
    """
    if code not in ERRORS:
        return ERRORS["E028"]["template"].format(unknown_code=code)
    return ERRORS[code]["template"].format(**fmt)


def explain(code: str) -> str:
    """Format a human-readable explanation block for ``cupli explain <code>``."""
    spec = error_spec(code)
    return f"{code} — {spec['title']}\n  What: {spec['template']}\n  How:  {spec['hint']}\n"


def all_codes() -> list[str]:
    """Return all defined error codes in ascending order."""
    return sorted(ERRORS)


class CupliError(Exception):
    """Structured cupli error.

    Carries a catalogue code plus formatting kwargs. The pretty-rendering layer
    reads ``.code`` to fetch the hint and optional source-line context.

    Attributes:
        code: catalogue code (e.g. ``"E001"``).
        fmt: keyword arguments forwarded to the error template.
    """

    def __init__(self, code: str, **fmt: object) -> None:
        """Initialise with a catalog code and formatting kwargs."""
        self.code = code
        self.fmt: dict[str, object] = dict(fmt)
        self._spec = error_spec(code)
        super().__init__(f"{code}: {error_message(code, **self.fmt)}")

    @property
    def title(self) -> str:
        """Short title from the catalog."""
        return self._spec["title"]

    @property
    def hint(self) -> str:
        """Remediation hint from the catalog."""
        return self._spec["hint"]


class ValidationFailure(CupliError):
    """Wraps ``pydantic.ValidationError`` with file + line/col context.

    Attributes:
        file: path to the YAML file that failed validation.
        errors_list: pydantic ``.errors()`` payload (each entry has ``loc``,
            ``msg``, ``type``, ``input``).
        marks: optional ``LineMarks`` for mapping pydantic locs to source lines.
    """

    def __init__(
        self,
        *,
        file: Path,
        errors_list: Sequence[Mapping[str, Any]],
        marks: LineMarks | None = None,
    ) -> None:
        """Initialise with file, error list, and optional source marks."""
        super().__init__("E002", file=str(file), count=len(errors_list))
        self.file = file
        self.errors_list = list(errors_list)
        self.marks = marks
