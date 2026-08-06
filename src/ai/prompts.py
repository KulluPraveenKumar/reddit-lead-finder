"""Prompt manager: versioned template files, rendered and hash-locked.

Prompts are code. They are versioned, diffed, and rolled back like code, and a
change to one is a change to system behaviour — which is why ``prompt_version``
is recorded on every artefact and every ``ai_calls`` row.

Templates are files rather than string literals for one practical reason: a
literal buried in a function cannot be diffed in a review, and a prompt change
that nobody reviewed is the single cheapest way to degrade output quality
without anyone noticing.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent / "prompts"

#: Every template must contain these. Enforced by a test, not by convention.
REQUIRED_SECTIONS = (
    "# Role",
    "# Task",
    "# Rules",
    "# JSON Shape",
)

#: DeepSeek's JSON mode requires the literal word "json" somewhere in the
#: prompt. Omitting it is a silent failure: the model answers in prose and the
#: repair ladder burns its retries on a problem no retry can fix.
JSON_MODE_SENTINEL = "json"

_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass(frozen=True)
class RenderedPrompt:
    stage: str
    version: int
    system: str
    user: str
    template_hash: str

    @property
    def system_hash(self) -> str:
        return hashlib.sha256(self.system.encode()).hexdigest()


@dataclass(frozen=True)
class PromptTemplate:
    stage: str
    version: int
    path: Path
    raw: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.raw.encode()).hexdigest()

    def split(self) -> tuple[str, str]:
        """Split into the frozen system half and the variable user half.

        ``# User`` is the boundary. Everything above it is identical on every
        call and is therefore what the provider's prefix cache can hit;
        everything below varies per item. Getting this split wrong does not
        break correctness — it silently destroys the cache saving, which is the
        largest single cost lever in the system.
        """
        marker = "\n# User\n"
        if marker in self.raw:
            system, user = self.raw.split(marker, 1)
            return system.strip(), user.strip()
        return self.raw.strip(), ""

    def variables(self) -> set[str]:
        return set(_VAR_PATTERN.findall(self.raw))


class PromptManager:
    def __init__(self, prompt_dir: Path | None = None):
        self.prompt_dir = prompt_dir or PROMPT_DIR
        self._cache: dict[tuple[str, int], PromptTemplate] = {}

    def path_for(self, stage: str, version: int) -> Path:
        return self.prompt_dir / f"{stage}.v{version}.md"

    def load(self, stage: str, version: int = 1) -> PromptTemplate:
        key = (stage, version)
        if key in self._cache:
            return self._cache[key]

        path = self.path_for(stage, version)
        if not path.exists():
            raise FileNotFoundError(f"No prompt template for stage {stage!r} v{version} at {path}")
        template = PromptTemplate(
            stage=stage, version=version, path=path, raw=path.read_text(encoding="utf-8")
        )
        self._cache[key] = template
        return template

    def render(self, stage: str, variables: dict[str, object], version: int = 1) -> RenderedPrompt:
        template = self.load(stage, version)
        system_raw, user_raw = template.split()

        system = self._substitute(system_raw, variables, stage, half="system")
        user = self._substitute(user_raw, variables, stage, half="user")

        return RenderedPrompt(
            stage=stage,
            version=version,
            system=system,
            user=user,
            template_hash=template.content_hash,
        )

    def _substitute(self, text: str, variables: dict[str, object], stage: str, *, half: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                raise KeyError(
                    f"Prompt {stage!r} ({half}) references {{{{{name}}}}} but no value was supplied"
                )
            return str(variables[name])

        return _VAR_PATTERN.sub(replace, text)

    def available(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for path in sorted(self.prompt_dir.glob("*.v*.md")):
            name = path.name[: -len(".md")]
            stage, _, version = name.rpartition(".v")
            if stage and version.isdigit():
                out.append((stage, int(version)))
        return out

    def latest_version(self, stage: str) -> int:
        versions = [v for s, v in self.available() if s == stage]
        if not versions:
            raise FileNotFoundError(f"No prompt templates found for stage {stage!r}")
        return max(versions)

    def validate(self, stage: str, version: int = 1) -> list[str]:
        """Return a list of problems. Empty means the template is well-formed."""
        problems: list[str] = []
        template = self.load(stage, version)
        raw = template.raw

        for section in REQUIRED_SECTIONS:
            if section not in raw:
                problems.append(f"missing required section {section!r}")

        if JSON_MODE_SENTINEL not in raw.lower():
            problems.append(
                "does not contain the literal word 'json', which JSON-mode providers require"
            )

        if "```" not in raw:
            problems.append("has no fenced example in # JSON Shape")

        system, _user = template.split()
        if "\n# User\n" not in raw:
            problems.append("has no '# User' boundary, so the whole prompt is treated as frozen")
        elif not system.strip():
            problems.append("has an empty system half, so there is no cacheable prefix")

        return problems
