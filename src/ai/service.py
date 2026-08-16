"""AIService — the only entry point to any model.

Business logic calls **domain methods**. It never sees a model name, a prompt, a
token, or a JSON body. Below this line lives everything vendor-shaped; above it,
nothing does.

Everything routes through one private ``_call()``, so caching, dedup, the budget
guard, rate limiting, retry, repair, cost recording and metrics are implemented
exactly once and inherited by all four domain methods. Four parallel
implementations would drift, and the one that drifted would be the one without
the budget check.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from ..db.models import AIStatus
from .cache import ResponseCache, cache_key, content_hash
from .concurrency import ConcurrencyPool, RateLimiter, RetryPolicy, run_with_retry
from .context import ContextBuilder, FrozenContext
from .cost import BudgetLimits, CostTracker, price_table_for
from .credentials import CredentialStore
from .errors import (
    AIDisabledError,
    InsufficientBalanceError,
    InvalidAPIKeyError,
    ProviderError,
)
from .metrics import AIMetrics
from .prompts import PromptManager
from .providers import ChatMessage, ChatRequest, LLMProvider, build_provider
from .providers.health import HealthRegistry
from .providers.router import ProviderRouter
from .repair import RepairBranch, ResponseRepairer
from .schemas import (
    BusinessKnowledgeOut,
    ConnectionResult,
    EnrichmentBatchOut,
    OutreachSuggestionOut,
    SectionRegenOut,
)

log = logging.getLogger(__name__)

#: Hard ceiling for the automatic output-budget escalation in ``_execute``.
#: Well under the model's 384K max output; this exists to stop a pathological
#: response doubling its way to a very large bill.
MAX_OUTPUT_CEILING = 32_000


@dataclass
class CallResult:
    value: Any
    from_cache: bool = False
    cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 1
    prefix_hash: str | None = None


class AIService:
    """The AI platform. Constructed once per process."""

    def __init__(
        self,
        settings,
        *,
        provider: LLMProvider | None = None,
        provider_name: str | None = None,
        cache: ResponseCache | None = None,
        limits: BudgetLimits | None = None,
        prompt_manager: PromptManager | None = None,
        session_factory=None,
    ):
        from .providers.registry import DEFAULT_PROVIDER

        self.settings = settings
        # Precedence: an injected provider (tests) > an explicit argument >
        # the operator's stored choice > the registry default. Reading the
        # stored choice matters: without it, selecting a provider in Settings
        # would persist and then be ignored on the next call.
        self.provider_name = (
            getattr(provider, "name", None)
            or provider_name
            or settings.get("ai.provider", None)
            or DEFAULT_PROVIDER
        )
        self.credentials = CredentialStore(settings, self.provider_name)
        self._provider = provider
        self._session_factory = session_factory

        self.prompts = prompt_manager or PromptManager()
        self.repairer = ResponseRepairer()
        self.cache = cache if cache is not None else ResponseCache(session_factory)
        self.metrics = AIMetrics()
        self.gate = None  # wired in Phase 6

        self.limits = limits or BudgetLimits(
            max_cost_per_run_usd=float(settings.get("ai.limits.max_cost_per_run_usd", 2.00)),
            max_cost_per_day_usd=float(settings.get("ai.limits.max_cost_per_day_usd", 5.00)),
            max_calls_per_run=int(settings.get("ai.limits.max_calls_per_run", 500)),
            max_items_per_run=int(settings.get("ai.limits.max_items_per_run", 2000)),
        )
        self.cost = CostTracker(price_table_for(self.provider), self.limits)
        self._day_spend_loaded = False

        # Health and routing. The breaker exists so a degraded provider cannot
        # spend the whole run's latency budget proving it is still degraded.
        self.health = HealthRegistry(
            failure_threshold=int(settings.get("ai.circuit.failure_threshold", 3)),
            cooldown_seconds=float(settings.get("ai.circuit.cooldown_seconds", 60.0)),
        )
        configured_fallbacks = settings.get("ai.fallbacks", None)
        if isinstance(configured_fallbacks, str):
            configured_fallbacks = [f.strip() for f in configured_fallbacks.split(",") if f.strip()]
        self.router = ProviderRouter(
            settings,
            primary=self.provider_name,
            fallbacks=configured_fallbacks or [],
            health=self.health,
        )
        # Tests inject a provider directly; the router must serve that instance
        # rather than rebuilding one from a key it does not have.
        if provider is not None:
            self.router._providers[self.provider_name] = provider

        self.retry_policy = RetryPolicy(
            max_attempts=int(settings.get("ai.retry.max_attempts", 3)),
            base_delay=float(settings.get("ai.retry.base_delay", 1.0)),
        )
        self.rate_limiter = RateLimiter(
            rate_per_second=float(settings.get("ai.rate_limit_per_second", 8.0))
        )
        self.pool = ConcurrencyPool(
            initial=int(settings.get("ai.concurrency", 8)),
            floor=int(settings.get("ai.concurrency_floor", 1)),
            ceiling=int(settings.get("ai.concurrency_ceiling", 16)),
            rate_limiter=self.rate_limiter,
        )
        self.context_builder = ContextBuilder(
            cache_chunk_tokens=self.provider.capabilities.cache_chunk_tokens or 64
        )

    # ------------------------------------------------------------- provider

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            key = self.credentials.get_key()
            model = self.settings.get("ai.model", None)
            self._provider = build_provider(self.provider_name, key, model=model)
        return self._provider

    def refresh_provider(self) -> None:
        """Drop the cached provider so the next call picks up a new key."""
        if self._provider is not None and getattr(self._provider, "name", "") == "fake":
            return  # tests inject this deliberately
        self._provider = None

    @property
    def enabled(self) -> bool:
        try:
            return self.credentials.has_key()
        except AIDisabledError:
            return False

    def require_enabled(self) -> None:
        if not self.enabled:
            raise AIDisabledError(
                "AI features are disabled: no API key is configured. "
                "Add one on the Settings page. Scraping is unaffected."
            )

    # ------------------------------------------------------- domain methods

    def analyze_business(
        self,
        *,
        url: str,
        site_text: str,
        local_signals: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        project_id: int | None = None,
    ) -> BusinessKnowledgeOut:
        """URL -> the whole Business Knowledge Base, in ONE call."""
        return self.analyze_business_call(
            url=url,
            site_text=site_text,
            local_signals=local_signals,
            max_tokens=max_tokens,
            project_id=project_id,
        ).value

    def analyze_business_call(
        self,
        *,
        url: str,
        site_text: str,
        local_signals: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        project_id: int | None = None,
    ) -> CallResult:
        """:meth:`analyze_business`, with the call's metadata attached.

        The sibling exists because **P14 is the first phase whose acceptance
        criteria are about the call rather than the answer** —
        [34 §P14](../../docs/34-implementation-plan.md) requires *"**exactly
        one** ``ai_calls`` row … total cost **< $0.05** and displayed …
        re-analysis of an unchanged fingerprint makes **zero** calls"*. Those are
        ``from_cache`` and ``cost_usd``, and a caller that cannot see them cannot
        display the cost or prove the zero.

        :meth:`analyze_business` keeps returning the model, so the domain-method
        idiom the other three follow is unbroken and no existing caller changes.

        ``max_tokens`` defaults to ``ai.max_tokens.business_intelligence``
        ([34 §P14](../../docs/34-implementation-plan.md)'s **Config** row).
        Generous headroom on purpose: truncation is the one failure the repair
        ladder cannot fix, and unused headroom costs nothing.
        """
        return self._call(
            stage="business_intelligence",
            variables={
                "url": url,
                "site_text": site_text,
                "local_signals": json.dumps(local_signals or {}, sort_keys=True, indent=2),
            },
            output_model=BusinessKnowledgeOut,
            max_tokens=max_tokens
            or int(self.settings.get("ai.max_tokens.business_intelligence", 12000)),
            content_for_hash=site_text,
            project_id=project_id,
        )

    def regenerate_section(
        self,
        *,
        section_key: str,
        section_schema: str,
        sibling_context: str,
        url: str,
        site_text: str,
    ) -> SectionRegenOut:
        """Re-derive one BKB section, reusing persisted context."""
        return self._call(
            stage="section_regen",
            variables={
                "section_key": section_key,
                "section_schema": section_schema,
                "sibling_context": sibling_context,
                "url": url,
                "site_text": site_text,
            },
            output_model=SectionRegenOut,
            max_tokens=4000,
            content_for_hash=f"{section_key}\x1f{site_text}",
        ).value

    def enrich_batch(
        self,
        *,
        items: list[dict[str, Any]],
        business_context: str,
        frozen: FrozenContext | None = None,
    ) -> EnrichmentBatchOut:
        """Analyse a batch of Reddit items in one call.

        Results are matched back by the echoed ``id``, never by position. A
        length mismatch is raised so the caller can split and retry rather than
        accept a partial batch as complete.
        """
        rendered_items = json.dumps(items, sort_keys=True, ensure_ascii=False, indent=2)
        result = self._call(
            stage="lead_enrichment",
            variables={"business_context": business_context, "items": rendered_items},
            output_model=EnrichmentBatchOut,
            # Generous on purpose. Reasoning models spend output budget on
            # reasoning BEFORE emitting content, and a budget that only covers
            # the JSON produces empty content or a truncated object -- neither
            # of which the repair ladder can fix, because the fix is a bigger
            # budget. Measured 2026-07-31: a 1-item batch at max_tokens=900
            # returned empty content or unterminated JSON on 4 of 7 attempts.
            max_tokens=1200 * max(1, len(items)) + 1500,
            frozen=frozen,
            content_for_hash=rendered_items,
        ).value

        expected = {str(item["id"]) for item in items}
        returned = {r.id for r in result.results}
        if returned != expected:
            from .errors import SchemaValidationError

            missing = sorted(expected - returned)
            extra = sorted(returned - expected)
            raise SchemaValidationError(
                f"Batch id mismatch: {len(missing)} missing, {len(extra)} unexpected. "
                "The batch will be split and retried.",
                field_errors=[f"missing: {missing}", f"unexpected: {extra}"],
            )
        return result

    def suggest_outreach(
        self, *, business_context: str, lead: dict[str, Any], analysis: dict[str, Any]
    ) -> OutreachSuggestionOut:
        """A hint for a human. Never a draft to send."""
        return self._call(
            stage="outreach_suggestion",
            variables={
                "business_context": business_context,
                "lead": json.dumps(lead, sort_keys=True, indent=2),
                "analysis": json.dumps(analysis, sort_keys=True, indent=2),
            },
            output_model=OutreachSuggestionOut,
            max_tokens=1200,
            content_for_hash=json.dumps(lead, sort_keys=True),
        ).value

    # ----------------------------------------------------------- operations

    def test_connection(self) -> ConnectionResult:
        """One-token round trip. Persists the outcome to ``ai_provider_state``."""
        try:
            key = self.credentials.get_key()
        except AIDisabledError as exc:
            return ConnectionResult(ok=False, status=exc.outcome, error=exc.message)

        if not key:
            return ConnectionResult(
                ok=False,
                status=AIStatus.UNCONFIGURED,
                error="No API key configured. Add one to enable AI features.",
            )

        provider = self.provider
        provider.api_key = key
        result = provider.validate_credentials()

        if result.status == AIStatus.INVALID_KEY:
            self.credentials.mark_invalid(result.error)
        elif result.status == AIStatus.INSUFFICIENT_BALANCE:
            self.credentials.mark_insufficient_balance(result.error)
        elif result.ok:
            self.credentials._write_state(
                status=AIStatus.VALID,
                fingerprint=None,
                digest=None,
                model_id=result.model,
                context_window=result.context_window,
                latency_ms=result.latency_ms,
                error=None,
                validated=True,
                preserve_identity=True,
            )

        return ConnectionResult(
            ok=result.ok,
            model=result.model,
            context_window=result.context_window,
            latency_ms=result.latency_ms,
            validated_at=datetime.now(UTC).isoformat(),
            status=result.status,
            error=result.error,
        )

    def usage_summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": getattr(self.provider, "model", None),
            "enabled": self.enabled,
            "metrics": self.metrics.to_dict(),
            "health": self.metrics.health(),
            "run_cost_usd": round(self.cost.run_spend.cost_usd, 6),
            "day_cost_usd": round(self.cost.day_spend().cost_usd, 6),
            "limits": {
                "max_cost_per_run_usd": self.limits.max_cost_per_run_usd,
                "max_cost_per_day_usd": self.limits.max_cost_per_day_usd,
                "max_calls_per_run": self.limits.max_calls_per_run,
            },
            "cache": {
                "hit_ratio": round(self.cache.hit_ratio, 4),
                **self.cache.stats,
            },
            "concurrency": self.pool.current,
            "prices": self.cost.prices.to_dict(),
            "routing": self.router.status(),
        }

    def provider_comparison(
        self,
        *,
        prefix_tokens: int = 3500,
        item_tokens: int = 500,
        output_tokens: int = 250,
        items: int = 1000,
    ) -> list[dict]:
        """What the same workload would cost on each registered provider.

        Estimated from published price tables, not measured. Its job is to make
        a provider switch a decision with a number attached rather than a guess;
        the figures are only as good as the price tables, and the Settings page
        shows each one's verification date beside it.
        """
        from .cost import PriceTable
        from .providers.registry import selectable_descriptors

        rows = []
        for descriptor in selectable_descriptors():
            prices = descriptor.pricing
            table = PriceTable(
                input_cached=prices["input_cached"],
                input_uncached=prices["input_uncached"],
                output=prices["output"],
                verified_on=descriptor.pricing_verified_on,
            )
            warm = table.cost(prefix_tokens, item_tokens, output_tokens) * items
            cold = table.cost(0, prefix_tokens + item_tokens, output_tokens) * items
            health = self.health.for_provider(descriptor.name)
            rows.append(
                {
                    "provider": descriptor.name,
                    "display_name": descriptor.display_name,
                    "model": descriptor.default_model,
                    "configured": self.router.is_configured(descriptor.name),
                    "is_primary": descriptor.name == self.provider_name,
                    "warm_cache_usd": round(warm, 4),
                    "cold_cache_usd": round(cold, 4),
                    "cache_differential": (
                        round(prices["input_uncached"] / prices["input_cached"], 1)
                        if prices["input_cached"]
                        else None
                    ),
                    "supports_schema_enforcement": descriptor.cls.capabilities.supports_schema_enforcement,
                    "supports_batch_api": descriptor.cls.capabilities.supports_batch_api,
                    "context_window": descriptor.context_window,
                    "pricing_verified_on": descriptor.pricing_verified_on,
                    "health": health.to_dict(),
                }
            )
        return rows

    def _ensure_day_spend_loaded(self) -> None:
        """Seed today's spend from ``ai_calls`` before the first budget check.

        Without this the daily cap is a **per-process** limit, not a per-day one:
        restarting the dashboard would reset it, and a cap that a restart clears
        is not a cap. Loaded lazily rather than in ``__init__`` because the
        service is constructed before the database is necessarily queryable.

        Failure is non-fatal and logged: an unreadable history should degrade the
        cap to per-process, never block the call path entirely.
        """
        if self._day_spend_loaded:
            return
        self._day_spend_loaded = True
        try:
            from ..db.database import get_session
            from ..db.repositories.ai import AICallRepository

            session = get_session()
            try:
                usage = AICallRepository(session).usage_today()
            finally:
                session.close()
            self.cost.load_day_spend(usage["cost_usd"], usage["calls"])
            if usage["calls"]:
                log.info(
                    "resumed daily spend: $%.6f over %d calls today",
                    usage["cost_usd"],
                    usage["calls"],
                )
        except Exception:
            log.warning(
                "could not load today's AI spend; the daily cap applies to this "
                "process only until restart",
                exc_info=True,
            )

    # ------------------------------------------------------- THE call path

    def _call(
        self,
        *,
        stage: str,
        variables: dict[str, Any],
        output_model: type[BaseModel] | None,
        max_tokens: int = 4096,
        prompt_version: int | None = None,
        frozen: FrozenContext | None = None,
        content_for_hash: str | None = None,
        project_id: int | None = None,
    ) -> CallResult:
        self.require_enabled()
        self._ensure_day_spend_loaded()

        version = prompt_version or self.prompts.latest_version(stage)
        prompt = self.prompts.render(stage, variables, version)

        system = prompt.system
        if frozen is not None and frozen.text:
            # Frozen context goes ahead of the template so the longest possible
            # byte-identical run sits at the front of the request.
            system = f"{frozen.text}\n\n{system}"
        prefix_hash = ContextBuilder.hash_of(system)

        key = cache_key(
            provider=self.provider_name,
            model=getattr(self.provider, "model", ""),
            stage=stage,
            prompt_version=version,
            system=system,
            user=prompt.user,
        )

        cached = self.cache.get(key)
        if cached is not None:
            self.metrics.record_call(from_cache=True, prefix_hash=prefix_hash)
            return CallResult(
                value=output_model.model_validate(cached) if output_model else cached,
                from_cache=True,
                prefix_hash=prefix_hash,
            )

        item_hash = content_hash(content_for_hash) if content_for_hash else None
        if item_hash:
            by_content = self.cache.get_by_content(item_hash, stage, version)
            if by_content is not None:
                self.metrics.record_call(from_cache=True, prefix_hash=prefix_hash)
                return CallResult(
                    value=output_model.model_validate(by_content) if output_model else by_content,
                    from_cache=True,
                    prefix_hash=prefix_hash,
                )

        # Collapse concurrent identical requests to one provider call.
        is_leader, event = self.cache.guard.acquire(key)
        if not is_leader:
            from .cache import _MISSING

            payload = self.cache.guard.wait(key, event)
            if payload is _MISSING:
                # The leader finished and its bookkeeping was cleaned up before
                # this follower woke. The cache was written before publish, so
                # it is authoritative; fall back to it rather than guessing.
                payload = self.cache.get(key)
            if payload is not None and payload is not _MISSING:
                self.metrics.record_call(from_cache=True, prefix_hash=prefix_hash)
                return CallResult(
                    value=output_model.model_validate(payload) if output_model else payload,
                    from_cache=True,
                    prefix_hash=prefix_hash,
                )
            # Neither the guard nor the cache has it: the leader failed in a way
            # that left no trace. Compute it rather than returning None.
            is_leader = True

        try:
            result = self._execute(
                stage=stage,
                version=version,
                system=system,
                user=prompt.user,
                output_model=output_model,
                max_tokens=max_tokens,
                prefix_hash=prefix_hash,
                project_id=project_id,
            )
            payload = (
                result.value.model_dump() if hasattr(result.value, "model_dump") else result.value
            )
            self.cache.put(
                key,
                payload,
                provider=self.provider_name,
                model=getattr(self.provider, "model", ""),
                stage=stage,
                prompt_version=version,
                item_content_hash=item_hash,
            )
            self.cache.guard.publish(key, payload)
            return result
        except BaseException as exc:
            self.cache.guard.fail(key, exc)
            raise
        finally:
            self.cache.guard.release(key)

    def _execute(
        self,
        *,
        stage: str,
        version: int,
        system: str,
        user: str,
        output_model: type[BaseModel] | None,
        max_tokens: int,
        prefix_hash: str,
        project_id: int | None = None,
    ) -> CallResult:
        repair_hint: str | None = None
        branch_attempts: dict[RepairBranch, int] = {}
        total_attempts = 0
        total_cost = 0.0

        while True:
            total_attempts += 1

            # Estimate first: the guard must fire BEFORE the spend, not after.
            estimated = self.cost.estimate(
                prefix_tokens=len(system) // 4,
                item_tokens=len(user) // 4,
                output_tokens=max_tokens // 4,
                warm=total_attempts > 1,
            )
            self.cost.check_budget(estimated_cost=estimated)

            user_content = f"{user}\n\n{repair_hint}" if repair_hint else user
            request = ChatRequest(
                messages=[
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user_content),
                ],
                model=getattr(self.provider, "model", ""),
                max_tokens=max_tokens,
                json_mode=output_model is not None,
                timeout=(
                    float(self.settings.get("ai.timeout.connect", 10.0)),
                    float(self.settings.get("ai.timeout.read", 60.0)),
                ),
            )

            provider_health = self.health.for_provider(self.provider_name)
            try:
                response = run_with_retry(
                    lambda _attempt, _req=request: self.provider.chat(_req),
                    self.retry_policy,
                    on_retry=lambda exc, att, delay: log.warning(
                        "retrying %s after %s (attempt %d, %.1fs)",
                        stage,
                        type(exc).__name__,
                        att,
                        delay,
                    ),
                )
            except Exception as exc:
                # Recorded after the retry policy has given up: a fault that a
                # retry fixed is not evidence the provider is unhealthy.
                provider_health.record_failure(exc)
                raise
            provider_health.record_success(response.latency_ms)

            cost = self.cost.record(
                cached=response.input_tokens_cached,
                uncached=response.input_tokens_uncached,
                out=response.output_tokens,
                reported=response.reported_cost_usd,
            )
            total_cost += cost
            self.metrics.record_call(
                cached=response.input_tokens_cached,
                uncached=response.input_tokens_uncached,
                out=response.output_tokens,
                cost=cost,
                latency_ms=response.latency_ms,
                truncated=response.truncated,
                prefix_hash=prefix_hash,
            )

            # Truncation and reasoning-exhaustion are budget problems, not
            # content problems. Sending them down the repair ladder wastes two
            # attempts on a fault no rewording can fix.
            budget_starved = response.truncated or (
                not response.content.strip() and response.reasoning_tokens >= max_tokens * 0.9
            )
            if budget_starved and max_tokens < MAX_OUTPUT_CEILING:
                previous = max_tokens
                max_tokens = min(max_tokens * 2, MAX_OUTPUT_CEILING)
                log.warning(
                    "%s exhausted its output budget (%d tokens, %d of them reasoning); "
                    "retrying at %d",
                    stage,
                    previous,
                    response.reasoning_tokens,
                    max_tokens,
                )
                self._record_ai_call(
                    stage=stage,
                    version=version,
                    response=response,
                    cost=0.0,
                    outcome="truncated",
                    attempt=total_attempts,
                    prefix_hash=prefix_hash,
                    project_id=project_id,
                    error=f"output budget {previous} exhausted; retrying at {max_tokens}",
                )
                continue

            outcome = self.repairer.evaluate(response.content, output_model, attempt=total_attempts)
            if outcome.ok:
                # Recorded once, here -- not once on send and again on outcome.
                # Two rows per call would inflate every calls-per-1,000-posts
                # figure by the repair rate.
                self._record_ai_call(
                    stage=stage,
                    version=version,
                    response=response,
                    cost=cost,
                    outcome="ok",
                    attempt=total_attempts,
                    prefix_hash=prefix_hash,
                    project_id=project_id,
                )
                return CallResult(
                    value=outcome.value,
                    cost_usd=total_cost,
                    latency_ms=response.latency_ms,
                    attempts=total_attempts,
                    prefix_hash=prefix_hash,
                )

            branch = outcome.branch
            branch_attempts[branch] = branch_attempts.get(branch, 0) + 1
            self.metrics.record_repair(branch.value)
            self._record_ai_call(
                stage=stage,
                version=version,
                response=response,
                cost=cost,  # the failed attempt was still billed
                outcome=branch.value,
                attempt=total_attempts,
                prefix_hash=prefix_hash,
                project_id=project_id,
                error=outcome.error,
            )

            if branch_attempts[branch] > self.repairer.max_attempts:
                self.metrics.record_failure()
                raise ResponseRepairer.to_exception(outcome, response.content, total_attempts)

            log.info(
                "repairing %s: %s (branch attempt %d)", stage, branch.value, branch_attempts[branch]
            )
            repair_hint = outcome.retry_hint

    # -------------------------------------------------------------- recording

    def _record_ai_call(
        self,
        *,
        stage: str,
        version: int,
        response,
        cost: float,
        outcome: str,
        attempt: int,
        prefix_hash: str,
        project_id: int | None = None,
        error: str | None = None,
    ) -> None:
        """Persist to ``ai_calls``. Never allowed to break the call it records.

        ``project_id`` has existed on this table since `0007` closed its deferred
        foreign key, and P14 is the first stage with a project to attribute a
        call to. It is what makes *"this project's BKB cost $0.0x"* a query
        rather than a time window — the indirection
        [DI28](../../docs/DEFERRED-IMPROVEMENTS.md) records ``leads`` still
        living with.
        """
        try:
            from ..db.database import session_scope
            from ..db.models import AICall

            with session_scope() as session:
                session.add(
                    AICall(
                        provider=self.provider_name,
                        model=getattr(self.provider, "model", ""),
                        project_id=project_id,
                        stage=stage,
                        prompt_version=version,
                        prefix_hash=prefix_hash,
                        input_tokens_cached=response.input_tokens_cached,
                        input_tokens_uncached=response.input_tokens_uncached,
                        output_tokens=response.output_tokens,
                        cost_usd=cost,
                        surcharge_multiplier=self.cost.surcharge_multiplier,
                        latency_ms=response.latency_ms,
                        attempt=attempt,
                        outcome=outcome,
                        error=error,
                        created_at=datetime.now(UTC).replace(tzinfo=None),
                    )
                )
        except Exception:
            log.debug("could not record ai_call", exc_info=True)

    # ----------------------------------------------------------- error hooks

    def handle_provider_error(self, exc: ProviderError) -> None:
        """Reflect a mid-run credential failure into the provider state."""
        if isinstance(exc, InvalidAPIKeyError):
            self.credentials.mark_invalid(exc.message)
        elif isinstance(exc, InsufficientBalanceError):
            self.credentials.mark_insufficient_balance(exc.message)
