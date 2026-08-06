"""The three-branch repair ladder.

DeepSeek's JSON mode guarantees **syntax, not schema**. It will happily return
well-formed JSON with the wrong fields, an empty string, or a markdown-fenced
block. Each of those has a different fix, and applying the wrong one wastes a
retry:

* **empty content** -> perturb the prompt. Retrying an identical request that
  produced nothing tends to produce nothing again.
* **invalid JSON** -> strip fences first (by far the commonest cause), then tell
  the model what the parser said.
* **schema violation** -> the JSON parsed, so the model can read; give it the
  specific field errors rather than a generic "try again".

Two attempts per branch. A third almost never succeeds and costs real money on
every failing item.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from .errors import EmptyContentError, InvalidJSONError, SchemaValidationError

log = logging.getLogger(__name__)

MAX_ATTEMPTS_PER_BRANCH = 2

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


class RepairBranch(StrEnum):
    NONE = "none"
    EMPTY_CONTENT = "empty_content"
    INVALID_JSON = "invalid_json"
    SCHEMA = "schema_error"


@dataclass
class RepairOutcome:
    ok: bool
    value: Any = None
    branch: RepairBranch = RepairBranch.NONE
    #: Appended to the *user* half of the prompt on retry. Never the system
    #: half — mutating that would break the prefix cache for every later call.
    retry_hint: str | None = None
    error: str | None = None
    field_errors: list[str] | None = None


def strip_fences(text: str) -> str:
    """Remove a wrapping markdown fence. The commonest JSON-mode slip."""
    match = _FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def extract_json_object(text: str) -> str:
    """Salvage the outermost {...} from a response with prose around it.

    Brace-counting rather than a regex because JSON nests and regexes do not.
    String literals are tracked so a brace inside a quoted value does not
    confuse the depth count.
    """
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text


class ResponseRepairer:
    """Evaluates a raw response and decides which branch, if any, applies."""

    def __init__(self, max_attempts: int = MAX_ATTEMPTS_PER_BRANCH):
        self.max_attempts = max_attempts

    def evaluate(
        self,
        raw: str,
        output_model: type[BaseModel] | None,
        *,
        attempt: int = 1,
    ) -> RepairOutcome:
        # ---------------------------------------------------- branch 1: empty
        if raw is None or not raw.strip():
            return RepairOutcome(
                ok=False,
                branch=RepairBranch.EMPTY_CONTENT,
                error="Provider returned empty content",
                retry_hint=self._perturbation(attempt),
            )

        # --------------------------------------------- branch 2: invalid JSON
        candidate = strip_fences(raw)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as first_error:
            salvaged = extract_json_object(candidate)
            if salvaged != candidate:
                try:
                    parsed = json.loads(salvaged)
                except json.JSONDecodeError:
                    return self._invalid_json(first_error, raw)
            else:
                return self._invalid_json(first_error, raw)

        if output_model is None:
            return RepairOutcome(ok=True, value=parsed)

        # -------------------------------------------------- branch 3: schema
        try:
            validated = output_model.model_validate(parsed)
        except ValidationError as exc:
            field_errors = self._format_field_errors(exc)
            return RepairOutcome(
                ok=False,
                branch=RepairBranch.SCHEMA,
                error=f"Response did not match {output_model.__name__}",
                field_errors=field_errors,
                retry_hint=(
                    "Your previous response was valid json but had the wrong shape. "
                    "Fix exactly these problems and return the corrected json object:\n"
                    + "\n".join(f"- {e}" for e in field_errors)
                ),
            )

        return RepairOutcome(ok=True, value=validated)

    # ---------------------------------------------------------------- helpers

    def _invalid_json(self, error: json.JSONDecodeError, raw: str) -> RepairOutcome:
        excerpt = raw[:200].replace("\n", " ")
        return RepairOutcome(
            ok=False,
            branch=RepairBranch.INVALID_JSON,
            error=f"Invalid JSON: {error.msg} at line {error.lineno} column {error.colno}",
            retry_hint=(
                "Your previous response was not valid json. The parser reported: "
                f"{error.msg} (line {error.lineno}, column {error.colno}). "
                "Return only the json object, with no markdown fence and no text "
                f"before or after it. Your response began: {excerpt!r}"
            ),
        )

    @staticmethod
    def _format_field_errors(exc: ValidationError) -> list[str]:
        """Field-scoped messages. Generic ones do not help the model."""
        out: list[str] = []
        for error in exc.errors()[:10]:
            location = ".".join(str(p) for p in error["loc"]) or "(root)"
            out.append(f"{location}: {error['msg']}")
        return out

    @staticmethod
    def _perturbation(attempt: int) -> str:
        """Nudge an empty-response retry into a different sampling path."""
        nudges = [
            "Your previous response was empty. Return the complete json object now.",
            "Return the json object. Begin your response with the opening brace.",
        ]
        return nudges[min(attempt - 1, len(nudges) - 1)]

    @staticmethod
    def to_exception(outcome: RepairOutcome, raw: str, attempts: int):
        if outcome.branch is RepairBranch.EMPTY_CONTENT:
            return EmptyContentError(outcome.error or "empty content", raw=raw, attempts=attempts)
        if outcome.branch is RepairBranch.INVALID_JSON:
            return InvalidJSONError(outcome.error or "invalid json", raw=raw, attempts=attempts)
        return SchemaValidationError(
            outcome.error or "schema validation failed",
            field_errors=outcome.field_errors,
            raw=raw,
            attempts=attempts,
        )
