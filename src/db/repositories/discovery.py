"""Watermark, due-queue and prescore persistence.

Repositories exist so query logic does not sprawl into handlers (AD-6). This one
also draws a second line that matters more here than elsewhere: **it owns every
statement discovery issues, and none of the modules that decide anything hold a
session.** ``watermarks.py`` and ``policy.py`` are pure functions over value
objects, so the decision to poll, the diff, and the overflow test can all be
exercised without a database -- and, more importantly, cannot accidentally keep
a transaction open across a network fetch (T0/K13).

The ``IN``-clause lookup in :meth:`known_ids` is stage 2's whole cost: one query
per poll, no matter how many posts the feed carried.
"""

from __future__ import annotations

import datetime
import json

from sqlalchemy.orm import Session

from src.discovery.watermarks import WatermarkState

from ..models import DiscoveryWatermark, Lead, Prescore

#: SQLite's variable limit is 999 on older builds. A feed carries at most 100
#: ids, so this never chunks in practice -- but a caller that batches several
#: feeds together would silently hit it, and a wrong answer here reads as
#: "these posts are all new" and re-collects them.
_MAX_IN_CLAUSE = 500


class DiscoveryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- watermarks --------------------------------------------------------

    def get_watermark(
        self, subreddit: str, channel: str, query: str | None = None
    ) -> DiscoveryWatermark | None:
        return (
            self.session.query(DiscoveryWatermark)
            .filter(
                DiscoveryWatermark.subreddit == subreddit,
                DiscoveryWatermark.channel == channel,
                DiscoveryWatermark.query.is_(None)
                if query is None
                else DiscoveryWatermark.query == query,
            )
            .one_or_none()
        )

    def state_of(
        self, subreddit: str, channel: str, query: str | None = None
    ) -> WatermarkState | None:
        """The row as the value object the pure functions take.

        Returning a detached value rather than the ORM row is what keeps
        ``watermarks.diff`` and ``policy.next_interval`` free of the session.
        """
        row = self.get_watermark(subreddit, channel, query)
        if row is None:
            return None
        return WatermarkState(
            last_seen_fullname=row.last_seen_fullname,
            last_seen_utc=row.last_seen_utc,
            consecutive_empty=row.consecutive_empty or 0,
            observed_rate_per_hour=row.observed_rate_per_hour,
        )

    def save_watermark(
        self,
        subreddit: str,
        channel: str,
        state: WatermarkState,
        *,
        query: str | None = None,
        polled_at: datetime.datetime | None = None,
        next_poll_at: datetime.datetime | None = None,
    ) -> DiscoveryWatermark:
        """Upsert the watermark for one channel.

        Idempotent by construction (R9): every field is *assigned* from the
        computed state rather than incremented in place, so replaying a poll
        lands on the same row instead of double-counting it.
        """
        row = self.get_watermark(subreddit, channel, query)
        if row is None:
            row = DiscoveryWatermark(subreddit=subreddit, channel=channel, query=query)
            self.session.add(row)

        row.last_seen_fullname = state.last_seen_fullname
        row.last_seen_utc = state.last_seen_utc
        row.consecutive_empty = state.consecutive_empty
        row.observed_rate_per_hour = state.observed_rate_per_hour
        if polled_at is not None:
            row.last_polled_at = polled_at
        if next_poll_at is not None:
            row.next_poll_at = next_poll_at
        return row

    def due(self, now: datetime.datetime, limit: int = 50) -> list[DiscoveryWatermark]:
        """Channels whose next poll has come round.

        A never-polled channel has ``next_poll_at IS NULL`` and is due
        immediately -- that is what makes a cold start happen without a separate
        bootstrap path.
        """
        return (
            self.session.query(DiscoveryWatermark)
            .filter(
                (DiscoveryWatermark.next_poll_at.is_(None))
                | (DiscoveryWatermark.next_poll_at <= now)
            )
            .order_by(DiscoveryWatermark.next_poll_at.asc().nullsfirst())
            .limit(limit)
            .all()
        )

    # -- the stage 2 lookup ------------------------------------------------

    def known_ids(self, reddit_ids: list[str]) -> set[str]:
        """Which of these posts do we already have? One query (stage 2).

        Chunked against the SQL variable limit rather than assuming a feed is
        small: exceeding it raises on some builds and, worse, would otherwise
        need a caller to remember the ceiling.
        """
        found: set[str] = set()
        unique = [rid for rid in dict.fromkeys(reddit_ids) if rid]
        for start in range(0, len(unique), _MAX_IN_CLAUSE):
            chunk = unique[start : start + _MAX_IN_CLAUSE]
            found.update(
                rid
                for (rid,) in self.session.query(Lead.reddit_id).filter(Lead.reddit_id.in_(chunk))
            )
        return found

    # -- prescores ---------------------------------------------------------

    def add_prescore(
        self,
        run_id: int,
        lead_id: int,
        *,
        total: float,
        components: dict,
        gate_decision: str,
        gate_reason: str | None = None,
        stage: str = "metadata",
    ) -> Prescore:
        """One triage decision, admitted or rejected.

        **Rejections are stored too, and that is the point** (R11, AD-10b). A
        gate that discards items without recording which ones cannot be
        measured, and an unmeasurable gate is one nobody can prove is not
        losing leads. The 2% holdout *audit* over these rows is P11's; P6's
        obligation is to make it possible by writing them.
        """
        row = Prescore(
            run_id=run_id,
            lead_id=lead_id,
            total=total,
            components_json=json.dumps(components, sort_keys=True),
            stage=stage,
            gate_decision=gate_decision,
            gate_reason=gate_reason,
            holdout_sampled=False,
        )
        self.session.add(row)
        return row

    def prescore_exists(self, run_id: int, lead_id: int, stage: str = "metadata") -> bool:
        """Has this item already been triaged in this run?

        The idempotence guard for a re-claimed job (R9): without it, a lease
        expiry mid-poll would write a second prescore row for every item it had
        already judged, and the funnel counts would double.
        """
        return (
            self.session.query(Prescore.id)
            .filter(
                Prescore.run_id == run_id,
                Prescore.lead_id == lead_id,
                Prescore.stage == stage,
            )
            .first()
            is not None
        )

    def counts_by_decision(self, run_id: int, stage: str = "metadata") -> dict[str, int]:
        """The funnel, as SQL rather than as loaded rows."""
        from sqlalchemy import func

        rows = (
            self.session.query(Prescore.gate_decision, func.count(Prescore.id))
            .filter(Prescore.run_id == run_id, Prescore.stage == stage)
            .group_by(Prescore.gate_decision)
            .all()
        )
        return dict(rows)
