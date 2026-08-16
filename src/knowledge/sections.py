"""Per-section validation — the mechanism behind P14's failure isolation.

[34 §P14](../../docs/34-implementation-plan.md) task 3: *"**Per-section
validation** — a failure marks that section ``incomplete``, the other 22
persist"*. This module is the *"per-section"* half. The other half is the
deliberately lenient :class:`~src.ai.schemas.BusinessKnowledgeOut` envelope,
whose docstring explains why a strict envelope makes two of the phase's
acceptance criteria jointly unsatisfiable.

**The division of labour, once:**

```
provider JSON
   │
   ├─ BusinessKnowledgeOut   lenient   → always validates → ONE ai_calls row
   │                                     (the repair ladder is reserved for
   │                                      malformed or truncated JSON)
   └─ validate_sections()    strict    → 23 independent verdicts, one each
                                         → ok | incomplete, and never both
```

⚠ **Nothing here raises on bad content.** A section that cannot be validated
comes back with ``status='incomplete'`` and the reason in ``error``; it does not
propagate. That is the entire point — an exception escaping this module would
take the other 22 sections with it, which is the failure the phase exists to
prevent.

**Three sections have a typed table and therefore no payload.**
``buyer_personas``, ``pain_points`` and ``buying_signals`` store their content in
``personas``, ``pain_points`` and ``intent_signals``, so their
``bkb_sections.payload_json`` is ``NULL`` — enforced by
``ck_bkb_sections_payload_null_rule``, not by convention (05 §5.1b).
``ideal_customer_profiles`` is **deliberately not** one of them: there is no
``icps`` table, so its payload is the only copy an ICP has.

## ⚠ Why the section models live here and not in ``src/ai/schemas.py``

[R3](../../docs/ARCHITECTURE_FREEZE.md) puts ``src/knowledge/`` inside grep
fence 2: **this package never imports ``src.ai``**, and
``tests/test_boundaries.py::test_the_knowledge_package_is_inside_the_ai_fence``
enforces it over every file here. So the strict per-section models cannot be
imported from the AI layer, and they are defined below instead.

That is the *correct* home rather than a workaround, and the split is the same
one [P14-DECISION-ANALYSIS §D4](../../docs/P14-DECISION-ANALYSIS.md) draws:

* **``src/ai/schemas.py`` owns the envelope** — what a *provider response* is
  allowed to look like, deliberately lenient.
* **``src/knowledge/`` owns the sections** — what the *knowledge base* is,
  strictly. The BKB's shape is the BKB's business, and a section schema that
  lived in the AI layer would make the knowledge base's definition depend on the
  thing that happens to fill it. That is exactly what R3 is for.

The four models P1 shipped in ``src/ai/schemas.py`` (``PersonaOut``,
``PainPointOut``, ``BuyingSignalOut``, ``CompetitorOut``) **had no importer** and
were moved here rather than copied, so there is one definition, not two.
:data:`SLUG_PATTERN` is the one thing genuinely duplicated across the fence —
five lines of regex, which is what a fence costs and is cheaper than the
dependency it would otherwise create.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.db.models import BKB_SECTION_KEYS, BKB_TYPED_SECTION_KEYS

log = logging.getLogger(__name__)

#: Lowercase kebab-case. **Duplicated from ``src/ai/schemas.py`` across the R3
#: fence, deliberately** — see this module's docstring. The two must agree, and
#: ``test_the_slug_pattern_agrees_across_the_fence`` is what makes that a test
#: rather than a hope.
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_slug(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not SLUG_PATTERN.match(value):
        raise ValueError(f"{value!r} is not a valid slug (lowercase kebab-case)")
    return value


class StrictSection(BaseModel):
    """Rejects unknown fields.

    A model inventing an extra key means the prompt and the schema have drifted
    apart. Silently ignoring it lets the drift accumulate until something
    important goes missing — and *here*, unlike at the envelope, rejecting costs
    one section rather than all 23, which is what makes strictness affordable.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------- the 23 shapes


class CompanyOverviewOut(StrictSection):
    summary: str = ""
    founded_context: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ProductServiceOut(StrictSection):
    name: str
    description: str = ""


class FeatureSetOut(StrictSection):
    product: str = ""
    capabilities: list[str] = Field(default_factory=list)


class PricingPositioningOut(StrictSection):
    model: Literal["free", "freemium", "tiered", "enterprise", "unknown"] = "unknown"
    posture: str = ""
    price_points: list[str] = Field(default_factory=list)


class IndustryOut(StrictSection):
    primary: str = ""
    adjacent: list[str] = Field(default_factory=list)


class TargetMarketOut(StrictSection):
    segment: Literal["B2B", "B2C", "both"] = "B2B"
    company_sizes: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    geographies: list[str] = Field(default_factory=list)


class ICPOut(StrictSection):
    """An ideal customer profile.

    ⚠ **There is no ``icps`` table**, so this section's ``payload_json`` is the
    only copy of an ICP that exists — 05 §5.1b flags exactly that mistake, and
    ``ck_bkb_sections_payload_null_rule`` deliberately does not exempt it.
    """

    slug: str
    name: str
    firmographics: dict = Field(default_factory=dict)
    trigger_events: list[str] = Field(default_factory=list)
    disqualifiers: list[str] = Field(default_factory=list)

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class PersonaOut(StrictSection):
    slug: str
    name: str
    job_title: str = ""
    seniority: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    where_they_ask: list[str] = Field(default_factory=list)

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class PainPointOut(StrictSection):
    slug: str
    title: str
    description: str = ""
    severity: int = Field(default=3, ge=1, le=5)
    frequency: int = Field(default=3, ge=1, le=5)
    how_people_phrase_it: list[str] = Field(default_factory=list)

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class JobToBeDoneOut(StrictSection):
    type: Literal["functional", "emotional", "social"] = "functional"
    statement: str


class ValuePropositionOut(StrictSection):
    claim: str
    answers_pain: str | None = None

    _slug = field_validator("answers_pain")(classmethod(lambda cls, v: _validate_slug(v)))


class CompetitorOut(StrictSection):
    slug: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    context: str = ""

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class AlternativeSolutionOut(StrictSection):
    name: str
    why_people_use_it: str = ""


class SearchIntentOut(StrictSection):
    shape: Literal["informational", "comparison", "transactional", "troubleshooting"] = (
        "informational"
    )
    examples: list[str] = Field(default_factory=list)


class BuyingSignalOut(StrictSection):
    slug: str
    label: str
    tier: Literal["high", "medium", "low"] = "medium"
    example_phrases: list[str] = Field(default_factory=list)

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class ObjectionOut(StrictSection):
    objection: str
    typical_phrasing: str = ""


class OutreachAngleOut(StrictSection):
    persona: str | None = None
    pain: str | None = None
    angle: str

    @field_validator("persona", "pain")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        return _validate_slug(value)


#: ``bkb_sections.status``. The column's own comment says ``ok|incomplete`` and
#: these are the only two values written.
STATUS_OK = "ok"
STATUS_INCOMPLETE = "incomplete"

#: The three container shapes a section can take. ``object`` is a single JSON
#: object validated as a whole; ``items`` is a list of typed objects; ``strings``
#: is a bare list of strings, which four of the 23 are.
SHAPE_OBJECT = "object"
SHAPE_ITEMS = "items"
SHAPE_STRINGS = "strings"


@dataclass(frozen=True)
class SectionSpec:
    """What one of the 23 sections must look like.

    ``min_items``/``max_items`` are the bounds
    [34 §P14](../../docs/34-implementation-plan.md)'s Acceptance row states —
    *"1–5 personas, 3–12 pains, 3–12 signals"* — plus the 1–3
    ``ideal_customer_profiles`` the prompt's Constraints block already carried.
    **They are checked here and nowhere else.** A bound enforced in the prompt
    alone is a request; a bound enforced here is a verdict.
    """

    key: str
    shape: str
    model: type[BaseModel] | None = None
    min_items: int | None = None
    max_items: int | None = None

    @property
    def typed(self) -> bool:
        """Does a typed table own this section's content? Then no payload."""
        return self.key in BKB_TYPED_SECTION_KEYS


#: The 23, in `BKB_SECTION_KEYS` order. **The order is not decorative** — P16
#: renders them as four contiguous bands, and `src/db/models.py` says so.
SECTION_SPECS: dict[str, SectionSpec] = {
    # Group A — Identity
    "company_overview": SectionSpec("company_overview", SHAPE_OBJECT, CompanyOverviewOut),
    "products_services": SectionSpec("products_services", SHAPE_ITEMS, ProductServiceOut),
    "features": SectionSpec("features", SHAPE_ITEMS, FeatureSetOut),
    "pricing_positioning": SectionSpec("pricing_positioning", SHAPE_OBJECT, PricingPositioningOut),
    "industry": SectionSpec("industry", SHAPE_OBJECT, IndustryOut),
    "target_market": SectionSpec("target_market", SHAPE_OBJECT, TargetMarketOut),
    # Group B — Buyer model
    "ideal_customer_profiles": SectionSpec(
        "ideal_customer_profiles", SHAPE_ITEMS, ICPOut, min_items=1, max_items=3
    ),
    "buyer_personas": SectionSpec(
        "buyer_personas", SHAPE_ITEMS, PersonaOut, min_items=1, max_items=5
    ),
    "pain_points": SectionSpec("pain_points", SHAPE_ITEMS, PainPointOut, min_items=3, max_items=12),
    "jobs_to_be_done": SectionSpec("jobs_to_be_done", SHAPE_ITEMS, JobToBeDoneOut),
    "value_propositions": SectionSpec("value_propositions", SHAPE_ITEMS, ValuePropositionOut),
    # Group C — Competitive and linguistic
    "competitor_references": SectionSpec("competitor_references", SHAPE_ITEMS, CompetitorOut),
    "alternative_solutions": SectionSpec(
        "alternative_solutions", SHAPE_ITEMS, AlternativeSolutionOut
    ),
    "customer_language": SectionSpec("customer_language", SHAPE_STRINGS),
    "reddit_terminology": SectionSpec("reddit_terminology", SHAPE_STRINGS),
    "search_intent": SectionSpec("search_intent", SHAPE_ITEMS, SearchIntentOut),
    "buying_signals": SectionSpec(
        "buying_signals", SHAPE_ITEMS, BuyingSignalOut, min_items=3, max_items=12
    ),
    "common_objections": SectionSpec("common_objections", SHAPE_ITEMS, ObjectionOut),
    # Group D — Activation and discovery
    "outreach_angles": SectionSpec("outreach_angles", SHAPE_ITEMS, OutreachAngleOut),
    "content_themes": SectionSpec("content_themes", SHAPE_STRINGS),
    "seo_entities": SectionSpec("seo_entities", SHAPE_STRINGS),
    "geo_entities": SectionSpec("geo_entities", SHAPE_STRINGS),
    "negative_signals": SectionSpec("negative_signals", SHAPE_STRINGS),
}


@dataclass(frozen=True)
class ValidatedSection:
    """One section's verdict. Twenty-three of these come back, always.

    ``payload`` is ``None`` for the three typed sections and JSON-ready for the
    other twenty, which is exactly the biconditional
    ``ck_bkb_sections_payload_null_rule`` asserts — so a row built from this
    dataclass satisfies the CHECK by construction rather than by the writer
    remembering to.
    """

    key: str
    payload: Any | None
    items: tuple[BaseModel, ...]
    status: str
    error: str | None = None
    confidence: float | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


def validate_sections(raw: Mapping[str, Any]) -> tuple[ValidatedSection, ...]:
    """Validate all 23 sections independently. Never raises.

    Returns exactly ``len(BKB_SECTION_KEYS)`` verdicts in that order, whatever
    the response contained — including for a response that contained nothing at
    all. A caller can therefore count 23 without checking, and a section going
    missing shows up as ``incomplete`` rather than as a shorter list.
    """
    return tuple(_validate_one(SECTION_SPECS[key], raw.get(key)) for key in BKB_SECTION_KEYS)


def _validate_one(spec: SectionSpec, value: Any) -> ValidatedSection:
    """One section, isolated. Every failure path lands on ``incomplete``."""
    try:
        if spec.shape == SHAPE_OBJECT:
            return _validate_object(spec, value)
        if spec.shape == SHAPE_STRINGS:
            return _validate_strings(spec, value)
        return _validate_items(spec, value)
    except Exception as exc:  # pragma: no cover - the belt to the braces above
        # Every branch below already handles its own failures; this exists so
        # that an unforeseen one costs ONE section rather than all 23, which is
        # the whole contract of this module.
        log.warning("section %s failed validation unexpectedly", spec.key, exc_info=True)
        return _incomplete(spec, f"unexpected error: {type(exc).__name__}: {exc}")


def _validate_object(spec: SectionSpec, value: Any) -> ValidatedSection:
    if value is None:
        return _incomplete(spec, "section absent from the response", payload={})
    if not isinstance(value, Mapping):
        return _incomplete(spec, f"expected a json object, got {type(value).__name__}", payload={})
    assert spec.model is not None
    try:
        model = spec.model.model_validate(dict(value))
    except ValidationError as exc:
        return _incomplete(spec, _format(exc), payload={})
    payload = model.model_dump()
    return ValidatedSection(
        key=spec.key,
        payload=payload,
        items=(model,),
        status=STATUS_OK,
        confidence=payload.get("confidence"),
    )


def _validate_strings(spec: SectionSpec, value: Any) -> ValidatedSection:
    if value is None:
        return _incomplete(spec, "section absent from the response", payload=[])
    if isinstance(value, str) or not isinstance(value, Sequence):
        return _incomplete(spec, f"expected a json array, got {type(value).__name__}", payload=[])

    strings = [v.strip() for v in value if isinstance(v, str) and v.strip()]
    if len(strings) != len(list(value)):
        # A non-string in a list of strings is a drift signal, not a fatality:
        # the strings that ARE strings are still knowledge, so they are kept and
        # the section says it is incomplete.
        return _incomplete(
            spec,
            f"{len(list(value)) - len(strings)} of {len(list(value))} entries were "
            "not non-empty strings and were dropped",
            payload=strings,
        )
    return ValidatedSection(key=spec.key, payload=strings, items=(), status=STATUS_OK)


def _validate_items(spec: SectionSpec, value: Any) -> ValidatedSection:
    """A list of typed objects — the shape 15 of the 23 sections take.

    Invalid entries are **dropped and reported**, not silently skipped and not
    fatal. Dropping is the same trade ``LeadAnalysisOut._check_slug_list``
    already makes for slug lists: one bad entry should cost one entry, and the
    ``incomplete`` status is what stops that from being invisible.
    """
    if value is None:
        return _incomplete(spec, "section absent from the response", payload=[])
    if isinstance(value, str) or not isinstance(value, Sequence):
        return _incomplete(spec, f"expected a json array, got {type(value).__name__}", payload=[])
    assert spec.model is not None

    items: list[BaseModel] = []
    problems: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            problems.append(f"[{index}] expected a json object, got {type(entry).__name__}")
            continue
        try:
            items.append(spec.model.model_validate(dict(entry)))
        except ValidationError as exc:
            problems.append(f"[{index}] {_format(exc)}")

    duplicate = _duplicate_slug(items)
    if duplicate is not None:
        # A duplicate slug is worse than a malformed one. Slugs are join keys
        # (`ux_personas_project_slug` is UNIQUE), so persisting two rows with the
        # same slug would either raise at the database or silently overwrite the
        # first — and which of the two you get depends on the upsert.
        problems.append(f"duplicate slug {duplicate!r}")
        items = _first_per_slug(items)

    payload = None if spec.typed else [item.model_dump() for item in items]

    if problems:
        return ValidatedSection(
            key=spec.key,
            payload=payload,
            items=tuple(items),
            status=STATUS_INCOMPLETE,
            error="; ".join(problems)[:2000],
        )

    bound = _bounds_error(spec, len(items))
    if bound is not None:
        return ValidatedSection(
            key=spec.key,
            payload=payload,
            items=tuple(items),
            status=STATUS_INCOMPLETE,
            error=bound,
        )

    return ValidatedSection(key=spec.key, payload=payload, items=tuple(items), status=STATUS_OK)


# ------------------------------------------------------------------- support


def _bounds_error(spec: SectionSpec, count: int) -> str | None:
    if spec.min_items is not None and count < spec.min_items:
        return f"expected at least {spec.min_items} entries, got {count}"
    if spec.max_items is not None and count > spec.max_items:
        return f"expected at most {spec.max_items} entries, got {count}"
    return None


def _duplicate_slug(items: Sequence[BaseModel]) -> str | None:
    seen: set[str] = set()
    for item in items:
        slug = getattr(item, "slug", None)
        if slug is None:
            continue
        if slug in seen:
            return slug
        seen.add(slug)
    return None


def _first_per_slug(items: Sequence[BaseModel]) -> list[BaseModel]:
    """Keep the first occurrence of each slug, in order.

    First rather than last, so the result does not depend on how many duplicates
    the model emitted — and so two runs over the same response agree.
    """
    seen: set[str] = set()
    kept: list[BaseModel] = []
    for item in items:
        slug = getattr(item, "slug", None)
        if slug is not None:
            if slug in seen:
                continue
            seen.add(slug)
        kept.append(item)
    return kept


def _incomplete(spec: SectionSpec, error: str, *, payload: Any = None) -> ValidatedSection:
    return ValidatedSection(
        key=spec.key,
        payload=None if spec.typed else payload,
        items=(),
        status=STATUS_INCOMPLETE,
        error=error[:2000],
    )


def _format(exc: ValidationError) -> str:
    """A Pydantic error as one short line.

    Stored in ``bkb_sections`` and rendered by P16, so it is written for the
    operator reading *"why is this section flagged?"*, not for a stack trace.
    """
    parts = []
    for error in exc.errors()[:4]:
        location = ".".join(str(p) for p in error.get("loc", ())) or "(root)"
        parts.append(f"{location}: {error.get('msg', 'invalid')}")
    return "; ".join(parts)


__all__ = [
    "SECTION_SPECS",
    "SHAPE_ITEMS",
    "SHAPE_OBJECT",
    "SHAPE_STRINGS",
    "STATUS_INCOMPLETE",
    "STATUS_OK",
    "SectionSpec",
    "ValidatedSection",
    "validate_sections",
]
