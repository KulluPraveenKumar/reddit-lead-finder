"""Read-side queries over the AI infrastructure tables.

Repositories exist so query logic does not sprawl into routes. Everything here
is aggregation over ``ai_calls`` — the source of truth for cost — computed in
SQL rather than by loading rows into Python, because this runs on every
dashboard poll.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func

from ..models import AICache, AICall, AIProviderState


def _naive_utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AICallRepository:
    def __init__(self, session):
        self.session = session

    def usage(self, *, since: datetime | None = None, run_id: int | None = None) -> dict[str, Any]:
        query = self.session.query(
            func.count(AICall.id),
            func.coalesce(func.sum(AICall.cost_usd), 0.0),
            func.coalesce(func.sum(AICall.input_tokens_cached), 0),
            func.coalesce(func.sum(AICall.input_tokens_uncached), 0),
            func.coalesce(func.sum(AICall.output_tokens), 0),
            func.avg(AICall.latency_ms),
        )
        if since is not None:
            query = query.filter(AICall.created_at >= since)
        if run_id is not None:
            query = query.filter(AICall.run_id == run_id)

        calls, cost, cached, uncached, out, latency = query.one()
        total_input = (cached or 0) + (uncached or 0)

        return {
            "calls": int(calls or 0),
            "cost_usd": round(float(cost or 0.0), 6),
            "input_tokens_cached": int(cached or 0),
            "input_tokens_uncached": int(uncached or 0),
            "output_tokens": int(out or 0),
            "mean_latency_ms": int(latency or 0),
            "prefix_cache_ratio": round((cached or 0) / total_input, 4) if total_input else 0.0,
        }

    def usage_today(self) -> dict[str, Any]:
        start = _naive_utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.usage(since=start)

    def usage_month(self) -> dict[str, Any]:
        start = _naive_utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.usage(since=start)

    def outcome_counts(self, *, days: int = 7) -> dict[str, int]:
        since = _naive_utcnow() - timedelta(days=days)
        rows = (
            self.session.query(AICall.outcome, func.count(AICall.id))
            .filter(AICall.created_at >= since)
            .group_by(AICall.outcome)
            .all()
        )
        return {outcome: int(count) for outcome, count in rows}

    def distinct_prefixes(self, *, days: int = 1) -> int:
        """More than one prefix hash in a window means the cache is being missed."""
        since = _naive_utcnow() - timedelta(days=days)
        return int(
            self.session.query(func.count(func.distinct(AICall.prefix_hash)))
            .filter(AICall.created_at >= since, AICall.prefix_hash.isnot(None))
            .scalar()
            or 0
        )

    def recent(self, limit: int = 25) -> list[AICall]:
        return self.session.query(AICall).order_by(AICall.created_at.desc()).limit(limit).all()


class AICacheRepository:
    def __init__(self, session):
        self.session = session

    def stats(self) -> dict[str, Any]:
        entries, hits = self.session.query(
            func.count(AICache.cache_key), func.coalesce(func.sum(AICache.hits), 0)
        ).one()
        return {"entries": int(entries or 0), "hits": int(hits or 0)}

    def purge(self) -> int:
        """Delete everything. Costs money to rebuild; changes no result."""
        deleted = self.session.query(AICache).delete()
        self.session.commit()
        return int(deleted)


class ProviderStateRepository:
    def __init__(self, session):
        self.session = session

    def get(self, provider: str) -> AIProviderState | None:
        return self.session.query(AIProviderState).filter_by(provider=provider).one_or_none()

    def all(self) -> list[AIProviderState]:
        return self.session.query(AIProviderState).all()
