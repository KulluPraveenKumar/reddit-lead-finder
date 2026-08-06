"""Price table, cost tracking, and the budget guard.

The guard checks **before** the call. Checking after would mean paying for the
request that broke the cap, which makes a cap an observation rather than a
limit.

Two independent ceilings, because cost and call count can diverge: a prompt-size
regression raises cost without raising calls, and a batching regression raises
calls without raising cost much. One dial would miss half the failures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from .errors import BudgetExceededError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriceTable:
    input_cached: float
    input_uncached: float
    output: float
    currency: str = "USD"
    verified_on: str = ""

    def cost(self, cached: int, uncached: int, out: int, multiplier: float = 1.0) -> float:
        return (
            (cached * self.input_cached / 1_000_000)
            + (uncached * self.input_uncached / 1_000_000)
            + (out * self.output / 1_000_000)
        ) * multiplier

    def to_dict(self) -> dict:
        return {
            "input_cached": self.input_cached,
            "input_uncached": self.input_uncached,
            "output": self.output,
            "currency": self.currency,
            "verified_on": self.verified_on,
        }


@dataclass
class BudgetLimits:
    max_cost_per_run_usd: float = 2.00
    max_cost_per_day_usd: float = 5.00
    max_calls_per_run: int = 500
    max_items_per_run: int = 2000


@dataclass
class Spend:
    cost_usd: float = 0.0
    calls: int = 0
    input_tokens_cached: int = 0
    input_tokens_uncached: int = 0
    output_tokens: int = 0
    cache_hits: int = 0

    def add(self, *, cost: float, cached: int, uncached: int, out: int, from_cache: bool = False) -> None:
        self.cost_usd += cost
        self.calls += 1
        self.input_tokens_cached += cached
        self.input_tokens_uncached += uncached
        self.output_tokens += out
        if from_cache:
            self.cache_hits += 1

    @property
    def prefix_cache_ratio(self) -> float:
        total = self.input_tokens_cached + self.input_tokens_uncached
        return self.input_tokens_cached / total if total else 0.0


class CostTracker:
    """Per-run and per-day spend, with the pre-call guard."""

    def __init__(
        self,
        price_table: PriceTable,
        limits: BudgetLimits | None = None,
        *,
        surcharge_multiplier: float = 1.0,
    ):
        self.prices = price_table
        self.limits = limits or BudgetLimits()
        # DeepSeek announced a 2x peak-hour surcharge that is not currently
        # active. Shipping the multiplier disabled means switching it on is a
        # config change, not a code change made under time pressure.
        self.surcharge_multiplier = surcharge_multiplier
        self.run_spend = Spend()
        self._day_spend: dict[date, Spend] = {}

    # ------------------------------------------------------------------ spend

    def day_spend(self, when: date | None = None) -> Spend:
        key = when or datetime.now(UTC).date()
        return self._day_spend.setdefault(key, Spend())

    def cost_of(self, cached: int, uncached: int, out: int) -> float:
        return self.prices.cost(cached, uncached, out, self.surcharge_multiplier)

    def record(
        self,
        *,
        cached: int,
        uncached: int,
        out: int,
        from_cache: bool = False,
        reported: float | None = None,
    ) -> float:
        """Record one call's spend.

        ``reported`` is the provider's own figure and wins when present. A
        gateway applies discounts -- prefix caching, negotiated rates -- that the
        token counts do not reveal, so computing locally would overstate the
        bill on exactly the calls we most want to measure.
        """
        if from_cache:
            cost = 0.0
        elif reported is not None:
            cost = reported
        else:
            cost = self.cost_of(cached, uncached, out)
        self.run_spend.add(cost=cost, cached=cached, uncached=uncached, out=out, from_cache=from_cache)
        self.day_spend().add(cost=cost, cached=cached, uncached=uncached, out=out, from_cache=from_cache)
        return cost

    def load_day_spend(self, spent_usd: float, calls: int = 0, when: date | None = None) -> None:
        """Seed today's total from the database at startup.

        Without this, restarting the process would reset the daily cap — which
        would make it a per-process limit rather than a per-day one.
        """
        spend = self.day_spend(when)
        spend.cost_usd = spent_usd
        spend.calls = calls

    # ------------------------------------------------------------------ guard

    def check_budget(self, *, estimated_cost: float = 0.0) -> None:
        """Raise before a call that would breach any ceiling."""
        run = self.run_spend
        day = self.day_spend()

        if run.calls + 1 > self.limits.max_calls_per_run:
            raise BudgetExceededError(
                f"Run call ceiling reached ({self.limits.max_calls_per_run} calls). "
                "Enrichment stopped; completed work is preserved.",
                limit_name="max_calls_per_run",
                limit=self.limits.max_calls_per_run,
                spent=run.calls,
            )

        projected_run = run.cost_usd + estimated_cost
        if projected_run > self.limits.max_cost_per_run_usd:
            raise BudgetExceededError(
                f"Run cost cap reached (${self.limits.max_cost_per_run_usd:.2f}). "
                f"Spent ${run.cost_usd:.4f}; this call would add ${estimated_cost:.4f}.",
                limit_name="max_cost_per_run_usd",
                limit=self.limits.max_cost_per_run_usd,
                spent=run.cost_usd,
            )

        projected_day = day.cost_usd + estimated_cost
        if projected_day > self.limits.max_cost_per_day_usd:
            raise BudgetExceededError(
                f"Daily cost cap reached (${self.limits.max_cost_per_day_usd:.2f}). "
                f"Spent ${day.cost_usd:.4f} today.",
                limit_name="max_cost_per_day_usd",
                limit=self.limits.max_cost_per_day_usd,
                spent=day.cost_usd,
            )

    def estimate(self, *, prefix_tokens: int, item_tokens: int, output_tokens: int, warm: bool = True) -> float:
        """Estimate one call. ``warm=False`` is the cold-cache upper bound."""
        if warm:
            return self.cost_of(prefix_tokens, item_tokens, output_tokens)
        return self.cost_of(0, prefix_tokens + item_tokens, output_tokens)

    def estimate_range(self, *, prefix_tokens: int, item_tokens: int, output_tokens: int) -> tuple[float, float]:
        """``(hot, cold)``.

        Quoted as a range because DeepSeek's caching is best-effort. A run
        quoting $0.03 and billing $0.11 because the cache was cold would destroy
        trust in every later estimate.
        """
        hot = self.estimate(prefix_tokens=prefix_tokens, item_tokens=item_tokens, output_tokens=output_tokens, warm=True)
        cold = self.estimate(prefix_tokens=prefix_tokens, item_tokens=item_tokens, output_tokens=output_tokens, warm=False)
        return hot, cold

    def reset_run(self) -> None:
        self.run_spend = Spend()


def price_table_for(provider) -> PriceTable:
    prices = provider.price_per_million()
    verified = getattr(provider, "PRICING_VERIFIED_ON", "")
    if not verified:
        import contextlib

        with contextlib.suppress(Exception):
            from .providers.registry import PROVIDER_REGISTRY

            verified = PROVIDER_REGISTRY[provider.name].pricing_verified_on
    return PriceTable(
        input_cached=prices["input_cached"],
        input_uncached=prices["input_uncached"],
        output=prices["output"],
        verified_on=verified,
    )
