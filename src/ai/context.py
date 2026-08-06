"""The frozen prefix — the single largest cost lever in the system.

DeepSeek prices cached input ~50x below uncached, and its prefix cache is
*implicit*: there is no marker to set, it simply matches the longest identical
prefix it has seen. That makes byte-stability of everything before the variable
part not a micro-optimisation but the cost model itself.

Three things destroy it, all of them easy to do by accident:

* a timestamp, UUID, or run id anywhere in the prefix
* iterating a dict whose key order varies between processes
* a float rendered differently on different platforms

``ContextBuilder`` exists to make all three impossible rather than merely
discouraged, and ``prefix_hash`` makes a regression visible in one query.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

#: Patterns that must never appear in a frozen prefix. Checked, not trusted.
_VOLATILE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ISO timestamp", re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")),
    ("UUID", re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)),
    ("epoch seconds", re.compile(r"\b1[6-9]\d{8}\b")),
    ("run/job id", re.compile(r"\b(run|job)[_-]?id\W{0,3}\d+", re.I)),
]


class VolatilePrefixError(ValueError):
    """Raised when something time-varying is about to be frozen into the prefix."""


@dataclass(frozen=True)
class FrozenContext:
    text: str
    prefix_hash: str
    token_estimate: int

    def __str__(self) -> str:
        return self.text


def stable_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, fixed separators, no ASCII escaping.

    ``sort_keys`` is the important part. Python dict order follows insertion,
    which follows whatever the caller happened to do, which can differ between
    runs — and a reordered prefix is a cache miss that looks like nothing at all.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def estimate_tokens(text: str) -> int:
    """~4 characters per token. Deliberately rough.

    Used for padding alignment and budget estimates, never for billing — the
    provider's reported counts are the only figures that reach ``ai_calls``.
    """
    return max(1, len(text) // 4)


def assert_stable(text: str, *, where: str = "prefix") -> None:
    """Fail loudly if volatile data is about to be frozen.

    Loudly on purpose. The alternative is a silent 50x cost increase that shows
    up as a slightly larger invoice a month later.
    """
    for label, pattern in _VOLATILE_PATTERNS:
        match = pattern.search(text)
        if match:
            raise VolatilePrefixError(
                f"{where} contains volatile data ({label}: {match.group(0)!r}). "
                "This would break prefix caching and multiply input cost by up to 50x."
            )


class ContextBuilder:
    """Builds the frozen prefix and keeps it byte-stable."""

    def __init__(self, *, cache_chunk_tokens: int = 64, pad_to_chunk: bool = True):
        self.cache_chunk_tokens = cache_chunk_tokens
        self.pad_to_chunk = pad_to_chunk

    def build(self, sections: dict[str, Any], *, verify: bool = True) -> FrozenContext:
        """Render ``sections`` into a stable, chunk-aligned prefix."""
        parts: list[str] = []
        for key in sorted(sections):
            value = sections[key]
            if value is None:
                continue
            rendered = value if isinstance(value, str) else stable_json(value)
            parts.append(f"## {key}\n{rendered}")

        text = "\n\n".join(parts)

        if verify and text:
            assert_stable(text, where="frozen context")

        if self.pad_to_chunk and text and self.cache_chunk_tokens > 0:
            text = self._pad(text)

        return FrozenContext(
            text=text,
            prefix_hash=hashlib.sha256(text.encode()).hexdigest(),
            token_estimate=estimate_tokens(text),
        )

    def _pad(self, text: str) -> str:
        """Pad to a chunk boundary with a constant filler.

        The cache works in 64-token chunks: a prefix ending mid-chunk leaves
        that chunk uncacheable. The padding is a fixed string, so it never
        varies and never carries information.
        """
        tokens = estimate_tokens(text)
        remainder = tokens % self.cache_chunk_tokens
        if remainder == 0:
            return text
        needed_chars = (self.cache_chunk_tokens - remainder) * 4
        return text + "\n" + ("." * max(0, needed_chars - 1))

    @staticmethod
    def hash_of(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()
