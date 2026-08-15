"""Holdout — the 2% audit that proves the metadata gate is honest.

[06c §6](../../docs/06c-local-first-pipeline.md), and
[freeze R11](../../docs/ARCHITECTURE_FREEZE.md): *"Every gate that discards items
must be audited. A 2% holdout applies to the admission gate **and** to metadata
triage."* P6 built the gate and deliberately did not build the audit — its
docstring says so: *"P6's obligation is to make that audit possible rather than
to run it."* This is the audit.

**Why it matters more here than anywhere else in the project.** A gate that
discards a good lead fails *silently* — [DI25](../../docs/DEFERRED-IMPROVEMENTS.md)
records that *"no page, log line or counter in this system reports the posts that
were never collected"*. This module is the first mechanism in the project capable
of **measuring** that false-positive rate rather than arguing about it, which is
why it is built **before** DI25's ``\\bhiring\\b`` defect is fixed: fixing the
regex first would delete the evidence that justifies the fix.

```
    2% of metadata-triage REJECTS
        -> fetched with their bodies (the feed already carried them)
        -> full-stage pre-scored
        -> persisted as real leads, source='holdout_audit'
        -> miss rate = how many the FULL gate would have admitted
```

⚠ **No AI is involved, and that is not a compromise.**
[34 §P11](../../docs/34-implementation-plan.md) requires ``SELECT COUNT(*) FROM
ai_calls WHERE run_id=?`` to be **0**, so *"would have qualified"* cannot mean
*"the model said ``is_lead``"* as [06c §6](../../docs/06c-local-first-pipeline.md)
describes for the later admission-gate audit. Here it means **the full-stage
deterministic gate admits what the metadata gate rejected** — which is exactly
the disagreement worth measuring at stage 3, because the metadata gate's whole
premise is deciding without a body. The AI-judged variant of this audit arrives
with ``gate_audits`` in revision ``0009`` and belongs to **P19/P20**.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

#: Rejection reasons that are **never sampled**.
#: [06c §6](../../docs/06c-local-first-pipeline.md): *"``already_analyzed``,
#: ``duplicate_exact``, ``duplicate_near`` and ``budget_exhausted`` are never
#: sampled — those rejections are provably correct, and auditing them would
#: waste calls proving arithmetic works."*
#:
#: ``no_title`` is added to that list here, and the addition is P11's rather than
#: 06c's: a post with no title has nothing for the full-stage gate to score, so
#: sampling it would enter a guaranteed non-miss into the denominator and bias
#: the published rate **downwards** — flattering the gate, which is the one
#: direction an audit must never be wrong in.
NEVER_SAMPLED = frozenset(
    {
        "already_analyzed",
        "duplicate_exact",
        "duplicate_near",
        "budget_exhausted",
        "no_title",
    }
)


def stable_hash(key: str) -> int:
    """A deterministic integer from a string, stable across processes.

    ``hash()`` is **not** usable: Python randomises string hashing per process
    (``PYTHONHASHSEED``), so the same run re-executed after a lease expiry would
    sample a different 2% and the audit would not be reproducible — which is the
    property [06c §6](../../docs/06c-local-first-pipeline.md) asks for by name:
    *"hash-based, so the audit is reproducible per run"*.

    SHA-256 rather than a cheaper digest because it is already the project's hash
    everywhere else (``dedupe/exact.py``, ``comments.body_hash``,
    ``ai_cache.cache_key``) and this runs once per rejected item, not per shingle.
    """
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def is_sampled(key: str, rate: float) -> bool:
    """Is this item in the audit sample?

    [06c §6](../../docs/06c-local-first-pipeline.md) writes the 2% case as
    ``stable_hash(i.content_hash) % 50 == 0``. Generalised to the configured
    ``gate.metadata_holdout_rate`` so the key is not decorative — a rate nothing
    reads is the *"documented capability that does not exist"* trap P6's
    ``density_threshold`` note names — and ``1 / 0.02 == 50`` reproduces 06c's
    literal modulus exactly, which ``test_the_default_rate_reproduces_06c_modulus_50``
    asserts.

    A rate of 0 samples nothing (the audit is off); a rate of 1 samples
    everything. Neither is a special case in the arithmetic below, but both are
    tested, because "off" must mean off rather than "every 1 in 0".
    """
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    return stable_hash(key) % round(1 / rate) == 0


@dataclass(frozen=True)
class MissRate:
    """The headline number, and what an operator can act on.

    [06c §6](../../docs/06c-local-first-pipeline.md)'s four fields.
    ``worst_reason`` is *"the actionable part — it tells the operator **which**
    rule is too aggressive, usually an over-broad negative keyword"*.
    """

    sampled: int
    would_have_qualified: int
    worst_reason: str | None = None
    by_reason: dict[str, int] | None = None

    @property
    def rate(self) -> float:
        """The ratio, in [0, 1]. **Zero samples is 0.0, and it is not a pass.**

        A run that sampled nothing has not demonstrated a gate miss rate below
        5%; it has demonstrated nothing. :attr:`measured` is what a caller must
        check before reporting the number, and the funnel renders *"not
        measured"* rather than *"0.0%"* when it is false — a zero is a
        measurement and a blank is an honest "not yet", which is the rule
        ``run_progress.html`` has carried since P3.
        """
        if self.sampled <= 0:
            return 0.0
        return self.would_have_qualified / self.sampled

    @property
    def measured(self) -> bool:
        return self.sampled > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "sampled": self.sampled,
            "would_have_qualified": self.would_have_qualified,
            "gate_miss_rate": round(self.rate, 4),
            "measured": self.measured,
            "worst_reason": self.worst_reason,
            "by_reason": dict(self.by_reason or {}),
        }


def audit_sample(rejected: Iterable[tuple[str, str]], rate: float) -> Iterator[tuple[str, str]]:
    """Yield the ``(key, reason)`` pairs to audit, skipping :data:`NEVER_SAMPLED`.

    ``key`` is whatever identifies the item stably — a ``reddit_id`` on the
    discovery path, a content hash elsewhere. It is the caller's choice because
    the two paths have different identifiers available, and passing the wrong one
    would degrade reproducibility silently rather than loudly; the callers pass
    ``reddit_id``, which ``leads.reddit_id`` makes ``UNIQUE``.
    """
    for key, reason in rejected:
        if reason in NEVER_SAMPLED:
            continue
        if is_sampled(key, rate):
            yield key, reason


def miss_rate(audited: Sequence[tuple[str, bool]]) -> MissRate:
    """Build the report from ``(rejection_reason, would_have_qualified)`` pairs."""
    by_reason: dict[str, int] = {}
    qualified = 0
    for reason, would_qualify in audited:
        if would_qualify:
            qualified += 1
            by_reason[reason] = by_reason.get(reason, 0) + 1

    worst = None
    if by_reason:
        # Ties broken by reason name so the field is deterministic across runs;
        # an arbitrary winner would make two identical runs report differently.
        worst = max(sorted(by_reason), key=lambda r: by_reason[r])

    return MissRate(
        sampled=len(audited),
        would_have_qualified=qualified,
        worst_reason=worst,
        by_reason=by_reason,
    )


__all__ = [
    "NEVER_SAMPLED",
    "MissRate",
    "audit_sample",
    "is_sampled",
    "miss_rate",
    "stable_hash",
]
