"""The Business Knowledge Base — the platform's core asset (AD-13).

P14 builds the first half: a website becomes 23 validated, persisted sections
from **one** AI call. P15 adds the entity registry, evidence, lifecycle and the
prefix builder; P16 adds the UI.

⚠️ **This package is inside grep fence 2 ([R3](../../docs/ARCHITECTURE_FREEZE.md)):
it never imports ``src.ai``**, and
``tests/test_boundaries.py::test_the_knowledge_package_is_inside_the_ai_fence``
enforces that over every file here. The AI service is **injected** into
:func:`~src.knowledge.bkb.analyze` as a parameter, never imported — which is why
that function takes ``service`` rather than constructing one.

The temptation this path carries is specific, and it is worth naming before P15
meets it: the BKB is *built from* a model's output, so every instinct says the
package that owns it should import the layer that produced it. **It must not.**
What arrives here is a validated value, not a call, and keeping it that way is
what lets the knowledge base be read, regenerated and reasoned about on a host
with no API key at all.

⚠ **``src.db.repositories.knowledge`` imports
:class:`~src.knowledge.sections.ValidatedSection` under ``TYPE_CHECKING`` only**,
and that is what keeps the import order below free rather than load-bearing:
``bkb`` reaches into that repository, which would otherwise reach back here and
close a cycle through this file. If that import is ever made unconditional, this
package will start depending on which of the two is imported first — which is a
failure that shows up as a confusing ``ImportError`` in one entry point and not
in another.
"""

from __future__ import annotations

from .bkb import (
    COST_BUDGET_USD,
    MARKUP_ABSENT_KEY,
    MARKUP_SIGNAL_KEYS,
    BKBResult,
    analyze,
    build_local_signals,
)
from .sections import (
    SECTION_SPECS,
    STATUS_INCOMPLETE,
    STATUS_OK,
    SectionSpec,
    ValidatedSection,
    validate_sections,
)

__all__ = [
    "COST_BUDGET_USD",
    "MARKUP_ABSENT_KEY",
    "MARKUP_SIGNAL_KEYS",
    "SECTION_SPECS",
    "STATUS_INCOMPLETE",
    "STATUS_OK",
    "BKBResult",
    "SectionSpec",
    "ValidatedSection",
    "analyze",
    "build_local_signals",
    "validate_sections",
]
