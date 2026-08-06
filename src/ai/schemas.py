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
SignalTier = Literal["high", "medium", "low"]


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


class PainPointOut(StrictModel):
    slug: str
    title: str
    description: str = ""
    severity: int = Field(default=3, ge=1, le=5)
    frequency: int = Field(default=3, ge=1, le=5)
    how_people_phrase_it: list[str] = Field(default_factory=list)

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class PersonaOut(StrictModel):
    slug: str
    name: str
    job_title: str = ""
    seniority: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    where_they_ask: list[str] = Field(default_factory=list)

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class BuyingSignalOut(StrictModel):
    slug: str
    label: str
    tier: SignalTier = "medium"
    example_phrases: list[str] = Field(default_factory=list)

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class CompetitorOut(StrictModel):
    slug: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    context: str = ""

    _slug = field_validator("slug")(classmethod(lambda cls, v: _validate_slug(v)))


class BusinessKnowledgeOut(BaseModel):
    """The 23-section BKB.

    ``extra="allow"`` here, unlike everywhere else: sections are typed
    individually in Phase 4, and rejecting a whole 23-section response because
    one section gained a field would be a poor trade during that build-out.
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    company_overview: dict = Field(default_factory=dict)
    products_services: list[dict] = Field(default_factory=list)
    features: list[dict] = Field(default_factory=list)
    pricing_positioning: dict = Field(default_factory=dict)
    industry: dict = Field(default_factory=dict)
    target_market: dict = Field(default_factory=dict)
    ideal_customer_profiles: list[dict] = Field(default_factory=list)
    buyer_personas: list[PersonaOut] = Field(default_factory=list)
    pain_points: list[PainPointOut] = Field(default_factory=list)
    jobs_to_be_done: list[dict] = Field(default_factory=list)
    value_propositions: list[dict] = Field(default_factory=list)
    competitor_references: list[CompetitorOut] = Field(default_factory=list)
    alternative_solutions: list[dict] = Field(default_factory=list)
    customer_language: list[str] = Field(default_factory=list)
    reddit_terminology: list[str] = Field(default_factory=list)
    search_intent: list[dict] = Field(default_factory=list)
    buying_signals: list[BuyingSignalOut] = Field(default_factory=list)
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
