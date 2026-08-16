"""Pydantic output models — the schema enforcement DeepSeek does not provide.

JSON mode guarantees syntax only. These models are therefore not defensive
extras; they are the *only* thing standing between a well-formed but wrong
response and the database.

Closed-set selection over open generation: a model asked to "identify the
persona" invents a new label every third call, while one asked to pick from six
slugs picks a slug. Slug fields are validated against a pattern here and
reconciled against the project's actual slugs in Phase 7.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

BuyingIntent = Literal["unaware", "problem_aware", "solution_aware", "evaluating", "ready_to_buy"]
Urgency = Literal["none", "low", "medium", "high", "critical"]
ICPMatch = Literal["none", "weak", "partial", "strong"]
Sentiment = Literal["negative", "frustrated", "neutral", "positive"]
Priority = Literal["low", "medium", "high", "urgent"]
# ``SignalTier`` was here and is **removed**, not merely unused: its only
# consumer, ``BuyingSignalOut``, moved to ``src/knowledge/sections.py`` under R3
# (D5), and it took the literal with it. A dead alias in a module about wire
# shapes is one a later reader wires something to.


class StrictModel(BaseModel):
    """Rejects unknown fields.

    A model inventing an extra key is a signal the prompt and schema have
    drifted apart. Silently ignoring it lets that drift accumulate until
    something important goes missing.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validate_slug(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not SLUG_PATTERN.match(value):
        raise ValueError(f"{value!r} is not a valid slug (lowercase kebab-case)")
    return value


# --------------------------------------------------------------- connectivity


class ConnectionResult(StrictModel):
    ok: bool
    model: str | None = None
    context_window: int | None = None
    latency_ms: int = 0
    validated_at: str | None = None
    status: str = "valid"
    error: str | None = None


# ------------------------------------------------------------------ evidence


class Evidence(StrictModel):
    quote: str = Field(default="", max_length=2000)
    source_url: str | None = None
    section: str | None = None


# ----------------------------------------------------- business intelligence
#
# Phase 4 fills these in against real sites. Phase 1 defines them so the
# schemas, the context shape, and the cache boundaries are settled before any
# consumer depends on them.


# ⚠️ **The 23 strict section models are NOT here — they are in
# ``src/knowledge/sections.py``**, and that is [R3](../../docs/ARCHITECTURE_FREEZE.md)
# rather than taste: ``src/knowledge/`` sits inside grep fence 2 and may never
# import ``src.ai``, so a section schema it must use cannot live in this module.
#
# It is also the right split on the merits. **This module owns the envelope** —
# what a *provider response* may look like. **``src/knowledge/`` owns the
# sections** — what the *knowledge base is*. A BKB whose definition lived in the
# AI layer would depend on the thing that happens to fill it.
#
# ``PersonaOut``, ``PainPointOut``, ``BuyingSignalOut`` and ``CompetitorOut``
# were defined here by P1 and **had no importer**; P14 **moved** them rather than
# copying them, so there is one definition and not two. See
# [P14-DECISION-ANALYSIS §D5](../../docs/P14-DECISION-ANALYSIS.md).


class BusinessKnowledgeOut(BaseModel):
    """The 23-section BKB envelope — **deliberately lenient**.

    ⚠ **Every field defaults and every container is untyped, and that is
    load-bearing rather than lazy.** Two of P14's acceptance criteria pull
    against each other on a strict envelope:

        Exactly ONE `ai_calls` row with stage='business_intelligence' per
        analysis  ·  a forced schema failure in ONE section leaves the other 22
        persisted

    ``AIService._record_ai_call`` writes one row **per attempt**, and
    ``_execute``'s repair ladder retries on any ``output_model`` failure. So if
    this envelope typed ``buyer_personas`` as ``list[PersonaOut]``, one
    malformed slug in one persona would fail all 23 sections, send the response
    down the repair ladder, and write a second and third ``ai_calls`` row — and
    the two criteria would be **jointly unsatisfiable**.

    Validation therefore happens in two places, not one:

    * **here**, loosely, so well-formed JSON always validates in one attempt and
      the repair ladder is reserved for what it was built for — malformed or
      truncated JSON, which no per-section logic can rescue;
    * **in :mod:`src.knowledge.sections`**, strictly, against the typed models
      above, one section at a time.

    The strict models were **not weakened — they were moved** to the section
    boundary, which is where per-section failure isolation requires them, and
    every one of them keeps its slug validator. See
    [P14-DECISION-ANALYSIS §D4](../../docs/P14-DECISION-ANALYSIS.md).
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    company_overview: dict = Field(default_factory=dict)
    products_services: list[dict] = Field(default_factory=list)
    features: list[dict] = Field(default_factory=list)
    pricing_positioning: dict = Field(default_factory=dict)
    industry: dict = Field(default_factory=dict)
    target_market: dict = Field(default_factory=dict)
    ideal_customer_profiles: list[dict] = Field(default_factory=list)
    buyer_personas: list[dict] = Field(default_factory=list)
    pain_points: list[dict] = Field(default_factory=list)
    jobs_to_be_done: list[dict] = Field(default_factory=list)
    value_propositions: list[dict] = Field(default_factory=list)
    competitor_references: list[dict] = Field(default_factory=list)
    alternative_solutions: list[dict] = Field(default_factory=list)
    customer_language: list[str] = Field(default_factory=list)
    reddit_terminology: list[str] = Field(default_factory=list)
    search_intent: list[dict] = Field(default_factory=list)
    buying_signals: list[dict] = Field(default_factory=list)
    common_objections: list[dict] = Field(default_factory=list)
    outreach_angles: list[dict] = Field(default_factory=list)
    content_themes: list[str] = Field(default_factory=list)
    seo_entities: list[str] = Field(default_factory=list)
    geo_entities: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    thin_content: bool = False


class SectionRegenOut(StrictModel):
    section_key: str
    payload: dict = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)


# ---------------------------------------------------------------- enrichment


class LeadAnalysisOut(StrictModel):
    """One analysed item.

    Note what is absent: a confidence score. The model emits categoricals and
    deterministic Python computes the 0-100 number, so re-ranking is free and
    calibration is possible.
    """

    id: str
    is_lead: bool = False
    summary: str = Field(default="", max_length=400)
    buying_intent: BuyingIntent = "unaware"
    urgency: Urgency = "none"
    icp_match: ICPMatch = "none"
    sentiment: Sentiment = "neutral"
    opportunity_score: int = Field(default=0, ge=0, le=10)
    recommended_priority: Priority = "low"

    matched_icp: str | None = None
    persona_slug: str | None = None
    matched_pain_slugs: list[str] = Field(default_factory=list)
    matched_signal_slugs: list[str] = Field(default_factory=list)
    competitor_mentions: list[str] = Field(default_factory=list)

    evidence_quote: str = Field(default="", max_length=2000)
    why_relevant: str = Field(default="", max_length=400)
    disqualifiers: list[str] = Field(default_factory=list)

    @field_validator("matched_icp", "persona_slug")
    @classmethod
    def _check_optional_slug(cls, value: str | None) -> str | None:
        return _validate_slug(value)

    @field_validator("matched_pain_slugs", "matched_signal_slugs", "competitor_mentions")
    @classmethod
    def _check_slug_list(cls, values: list[str]) -> list[str]:
        # Drop malformed slugs rather than failing the whole item: one bad slug
        # should cost one field, not an entire analysis and a retry.
        return [v for v in values if v and SLUG_PATTERN.match(v)]


class EnrichmentBatchOut(StrictModel):
    """The batch envelope.

    ``results`` is matched back to inputs by the echoed ``id``, never by
    position. A length mismatch is a batch failure that splits and retries.
    """

    results: list[LeadAnalysisOut] = Field(default_factory=list)


class OutreachSuggestionOut(StrictModel):
    angle: str = Field(default="", max_length=600)
    talking_points: list[str] = Field(default_factory=list)
    likely_objections: list[str] = Field(default_factory=list)
    caution: str = Field(default="", max_length=600)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


STAGE_MODELS: dict[str, type[BaseModel]] = {
    "business_intelligence": BusinessKnowledgeOut,
    "section_regen": SectionRegenOut,
    "lead_enrichment": EnrichmentBatchOut,
    "outreach_suggestion": OutreachSuggestionOut,
}
