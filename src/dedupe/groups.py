"""The cascade — three tiers in, one set of groups out, and the DI22 guarantee.

This is the module the other three exist for. It runs exact, then near, then
semantic; it picks a representative per group; and it upholds the one invariant
the schema cannot.

---

## DI22 — *"at most one group per run"*, which SQLite cannot express

[05 §5.4b](../../docs/05-database-plan.md) described ``dedup_members`` as *"a lead
or comment belongs to at most one group **per run**"*. What ``0006`` ships
enforces *"at most once **within** a group"* — two partial unique indexes on
``(group_id, lead_id)`` and ``(group_id, comment_id)``. The gap is **structural,
not an oversight**: ``dedup_members`` has no ``run_id``, the run is reachable only
through ``dedup_groups.run_id``, and SQLite cannot constrain uniqueness across a
join. Two groups from the same run can each claim the same lead and every index
stays satisfied.

P8 deliberately shipped **no test that appeared to check it**, on the grounds
that a test which retires the question is worse than the gap. It named P10 as the
owner, and this is P10.

The guarantee is therefore **structural in the write path, not a check bolted on
at the end**. :class:`_Clusters` holds a ``key -> cluster`` map and every tier
consults it before it may take an item, so a second claim is not rejected — it is
never constructed. :func:`validate_membership` then asserts the property
independently, and :func:`persist` refuses to write a result that fails it, so
the invariant cannot be lost by a caller that builds groups some other way.

---

## Complete linkage — the defect mutation testing found

A member joins a group only if it reaches the threshold against **every** member,
not merely against the one that matched it. The first implementation used single
linkage, and mutation **M35** survived against it; probing why produced a
**14-member group whose furthest pair was 0.445 similar**. Single linkage is
transitive closure in disguise, and two leads 0.445 apart sharing one AI analysis
is exactly the silent quality regression
[06c §4.4](../../docs/06c-local-first-pipeline.md) forbids. See
:meth:`_Clusters.attach`.

**No column was added.** [DEFERRED-IMPROVEMENTS DI22](../../docs/DEFERRED-IMPROVEMENTS.md)
records that adding ``run_id`` to ``dedup_members`` would be a
[freeze §11](../../docs/ARCHITECTURE_FREEZE.md) question; P10 did not need it,
so it was not asked.

---

## The correctness rule, restated where it can be broken

[06c §4.4](../../docs/06c-local-first-pipeline.md) — **group for analysis, score
individually.** Nothing in this module reads, writes or derives a per-item score.
Grouping produces ``dedup_groups`` and ``dedup_members`` rows and a
:class:`~src.rules.RuleResult` per non-representative, and that is all. The
``confidence_score`` column is P21's, and a group of N must still yield N
distinct scores when it arrives.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from src.db.models import DedupGroup, DedupMember, MinhashBand
from src.rules import RuleResult

from . import (
    KIND_LEAD,
    METHOD_EXACT,
    METHOD_MINHASH,
    METHOD_SEMANTIC,
    DedupItem,
    DedupSettings,
    ItemKey,
    duplicate,
    reason_for_method,
)
from .exact import group_exact, hash_item, normalise
from .minhash import LshIndex, bands, shingles, signature
from .semantic import Encoder, similar_pairs

log = logging.getLogger(__name__)


class MembershipError(RuntimeError):
    """An item was claimed by two groups — DI22's invariant, violated.

    A hard error and not a warning. The consequence of letting it through is
    that one lead is enriched under two different shared analyses, and the
    operator sees a *"similar discussions"* affordance that disagrees with
    itself depending on which group they arrived from.
    """


@dataclass(frozen=True)
class Group:
    """One dedup group, before it becomes rows.

    ``similarity`` is ``None`` for exact groups — they are not *similar*, they are
    *identical*, and ``dedup_groups.similarity`` is nullable precisely so that
    distinction survives. A ``1.0`` there would claim a measurement that was never
    taken.
    """

    method: str
    representative: ItemKey
    members: tuple[ItemKey, ...]
    similarity: float | None = None

    def __post_init__(self) -> None:
        if self.representative not in self.members:
            raise ValueError(
                f"representative {self.representative} is not among its own members "
                f"{self.members}; dedup_groups.representative_lead_id would point outside "
                "the group it heads"
            )

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def duplicates(self) -> tuple[ItemKey, ...]:
        """Members that are not the representative — the ones nothing enriches."""
        return tuple(k for k in self.members if k != self.representative)


@dataclass(frozen=True)
class CascadeResult:
    """Everything one pass of the cascade produced.

    ``content_hashes`` is returned even for ungrouped items because that hash is
    what [06c §5](../../docs/06c-local-first-pipeline.md)'s incremental
    enrichment keys on — ``(content_hash, prompt_version)``. Recomputing it in
    P19 would be free but duplicating the normalisation rules would not.
    """

    groups: tuple[Group, ...] = ()
    content_hashes: dict[ItemKey, str] = field(default_factory=dict)
    signatures: dict[ItemKey, tuple[int, ...]] = field(default_factory=dict)
    rejections: dict[ItemKey, RuleResult] = field(default_factory=dict)

    @property
    def grouped_keys(self) -> set[ItemKey]:
        return {k for g in self.groups for k in g.members}

    @property
    def representatives(self) -> tuple[ItemKey, ...]:
        return tuple(g.representative for g in self.groups)

    def collapse_rate(self, total_items: int) -> float:
        """Fraction of items removed from the enrichment set by grouping.

        ``0.0`` for an empty run rather than a ``ZeroDivisionError``: a run that
        collected nothing collapsed nothing, and a metric that raises on the
        quiet case is a metric that gets wrapped in a ``try`` and then ignored.
        """
        if total_items <= 0:
            return 0.0
        return sum(g.member_count - 1 for g in self.groups) / total_items


def _rank_key(item: DedupItem) -> tuple[float, float, float, int]:
    """Ordering for :func:`choose_representative`. Higher is better.

    [06c §4.3](../../docs/06c-local-first-pipeline.md) writes
    ``max(group, key=lambda i: (i.prescore.total, i.score or 0, i.created_utc))``.
    **``prescore`` does not exist yet** — ``src/scoring/prescore.py`` is P11's
    Files row and P11 depends on P10 — so :attr:`~src.dedupe.DedupItem.rank`
    carries it, defaults to ``None``, and the ordering falls back to
    ``(score, created_utc)``. Operator decision **D1**; P11 fills ``rank`` in
    without touching this signature.

    ``created_utc`` becomes a POSIX timestamp rather than being compared as a
    ``datetime``, because a corpus that mixes naive and aware datetimes raises
    ``TypeError`` on comparison — and the one thing representative selection must
    never do is fail the run over a timezone.

    The trailing ``row_id`` is the tie-break. Without it, two items equal on all
    three fields would be ordered by whatever ``max`` saw first, and the
    identical-lead-set criterion would depend on dictionary iteration order.
    """
    rank = float("-inf") if item.rank is None else float(item.rank)
    score = float("-inf") if item.score is None else float(item.score)
    when = _timestamp(item.created_utc)
    return (rank, score, when, item.row_id)


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    try:
        return value.timestamp()
    except (OverflowError, OSError, ValueError):
        # datetime.min on Windows raises rather than returning a negative epoch.
        return float("-inf")


def choose_representative(items: Sequence[DedupItem]) -> DedupItem:
    """The member that gets enriched. Highest ``(rank, score, created_utc, id)``.

    The representative is enriched and **the analysis is linked to every member**
    ([06c §4.3](../../docs/06c-local-first-pipeline.md)). Picking the wrong one
    costs quality, not correctness: every member still keeps its own score.
    """
    if not items:
        raise ValueError("a dedup group has at least one member")
    return max(items, key=_rank_key)


#: Tier order, loosest last. Used when a later tier adds a member to a group an
#: earlier tier opened: ``dedup_groups.method`` should name the **loosest**
#: evidence the group rests on, because that is the claim an operator is being
#: asked to trust. An exact group that gained a MinHash member is a MinHash
#: group; calling it exact would say its members are identical when one of them
#: is merely 0.87 similar.
_METHOD_RANK = {METHOD_EXACT: 0, METHOD_MINHASH: 1, METHOD_SEMANTIC: 2}


class _Clusters:
    """Mutable working state for :func:`build_groups`. Not part of the API.

    Exists because :class:`Group` is frozen and the cascade is **incremental**:
    a later tier may add a member to a group an earlier tier opened, and rebuilding
    a frozen dataclass on every attach would obscure the one property that matters
    here — **every key belongs to at most one cluster, at every moment**, which is
    DI22 upheld by construction rather than checked afterwards.
    """

    def __init__(self) -> None:
        self._members: list[list[ItemKey]] = []
        self._method: list[str] = []
        self._similarity: list[float | None] = []
        self._of: dict[ItemKey, int] = {}
        #: How each individual key joined, which is **not** its group's method.
        #: A group is described by the loosest evidence it rests on, but a member
        #: that arrived through tier 1 is an *exact* duplicate and P19's funnel
        #: must be able to count it as one. Reporting every member of an upgraded
        #: group as ``duplicate_near`` would move real ``duplicate_exact`` volume
        #: into the near bucket, and the two have very different implications:
        #: exact duplicates are reposts, near ones are separate conversations.
        self._joined_by: dict[ItemKey, str] = {}

    def holds(self, key: ItemKey) -> bool:
        return key in self._of

    def joined_by(self, key: ItemKey) -> str:
        return self._joined_by[key]

    def open(self, method: str, keys: Sequence[ItemKey], similarity: float | None) -> int:
        fresh = [k for k in keys if k not in self._of]
        index = len(self._members)
        self._members.append(list(fresh))
        self._method.append(method)
        self._similarity.append(similarity)
        for key in fresh:
            self._of[key] = index
            self._joined_by[key] = method
        return index

    def attach(
        self,
        method: str,
        key: ItemKey,
        matches: Sequence[tuple[ItemKey, float]],
        *,
        similarity: Callable[[ItemKey, ItemKey], float] | None = None,
        threshold: float = 0.0,
    ) -> None:
        """Add ``key`` to the best cluster among ``matches``, or open a new one.

        ⚠️ **Complete linkage: ``key`` joins a cluster only if it reaches
        ``threshold`` against *every* member, not merely against the one that
        matched it.** Found by mutation testing (M35) — the single-linkage version
        this replaced produced a **14-member group whose furthest member was 0.445
        similar to its representative**, measured 2026-08-14 on a graded corpus.

        Single linkage is transitive closure wearing a disguise: ``A~B`` at 0.90
        and ``B~C`` at 0.90 puts ``A`` and ``C`` in one group at 0.445, and they
        then **share one AI analysis**. That is precisely the silent quality
        regression [06c §4.4](../../docs/06c-local-first-pipeline.md) warns about,
        and [06c §4.2](../../docs/06c-local-first-pipeline.md) asks for *pairs
        above a threshold*, not for connected components.

        The cost is bounded and small: one comparison per existing member, and a
        group is a handful of items. ``similarity`` is injected rather than
        imported so this class stays independent of which tier is calling — tier 2
        passes the LSH index's estimator, tier 3 passes its cosine scores.

        When ``matches`` spans two clusters the best admissible one wins and the
        other is left alone; members of other clusters are never stolen, which is
        what keeps DI22 true.

        ⚠️ **Omitting ``similarity`` restores single linkage, silently.** With it
        ``None`` there is nothing to compare against, so :func:`admissible`
        returns ``True`` and the 0.445 behaviour above comes back. Both call
        sites in :func:`build_groups` pass it and M37–M39 guard them, but a
        **fourth tier that forgot to** would get no warning. It is a default
        rather than a required argument because tier 1 groups items that are
        byte-identical after normalisation, where the constraint is vacuous.
        """
        if key in self._of:
            return

        def admissible(candidate: ItemKey, index: int, matched: ItemKey | None = None) -> bool:
            """Does ``candidate`` reach ``threshold`` against every member of ``index``?

            ``matched`` is the member that already matched it above the threshold
            and is skipped — the caller measured that pair, and re-deriving it
            from the estimator would only reintroduce the sketch's ±0.05.

            **Takes the candidate as a parameter rather than closing over
            ``key``.** The first version of this closed over ``key`` and was then
            called for the *other* members being pulled in, so it checked the
            wrong item against the cluster and let a 0.781 pair through — a
            complete-linkage guard that was, for half its call sites, checking
            nothing.
            """
            if similarity is None:
                return True
            return all(
                member == matched or similarity(candidate, member) >= threshold
                for member in self._members[index]
            )

        best_index: int | None = None
        best_sim = -1.0
        for other, sim in matches:
            index = self._of.get(other)
            if index is not None and sim > best_sim and admissible(key, index, other):
                best_index, best_sim = index, sim

        if best_index is None:
            # A brand-new cluster is built under the same complete-linkage rule:
            # every candidate must reach `threshold` against everything already
            # admitted, not merely against `key`. Candidates arrive best-first
            # from the caller, so the greedy pass keeps the strongest matches.
            fresh = [key]
            best_sim = 0.0
            for other, sim in matches:
                if other in self._of:
                    continue
                if similarity is not None and any(
                    similarity(other, member) < threshold for member in fresh if member != key
                ):
                    continue
                fresh.append(other)
                best_sim = max(best_sim, sim)
            if len(fresh) < 2:
                return
            self.open(method, fresh, similarity=best_sim)
            return

        self._members[best_index].append(key)
        self._of[key] = best_index
        self._joined_by[key] = method
        for other, sim in matches:
            if other not in self._of and admissible(other, best_index):
                self._members[best_index].append(other)
                self._of[other] = best_index
                self._joined_by[other] = method
                best_sim = max(best_sim, sim)
        if _METHOD_RANK[method] > _METHOD_RANK[self._method[best_index]]:
            self._method[best_index] = method
        current = self._similarity[best_index]
        self._similarity[best_index] = best_sim if current is None else max(current, best_sim)

    def freeze(self, by_key: dict[ItemKey, DedupItem]) -> list[Group]:
        """Choose each cluster's representative and make it immutable."""
        out: list[Group] = []
        for members, method, similarity in zip(
            self._members, self._method, self._similarity, strict=True
        ):
            if len(members) < 2:
                continue
            ordered = tuple(members)
            rep = choose_representative([by_key[k] for k in ordered]).key
            out.append(Group(method, rep, ordered, similarity=similarity))
        return out


def build_groups(
    items: Iterable[DedupItem],
    settings: DedupSettings | None = None,
    *,
    encoder: Encoder | None = None,
) -> CascadeResult:
    """Run the three tiers and return the groups, hashes, signatures and rejections.

    Tiers run cheapest-first and **each may only claim items no earlier tier
    took** — which is both the performance argument and DI22's guarantee. A tier
    that could re-claim would produce two groups over one lead, and no index in
    ``0006`` would notice.

    Every tier is individually switchable, and switching one off can only ever
    produce *more* groups of size one — never a different lead set. That is what
    makes ``dedup.minhash_enabled: false`` and ``semantic_threshold: null``
    rollbacks rather than behaviour changes.
    """
    cfg = settings or DedupSettings()
    ordered = list(items)
    by_key = {item.key: item for item in ordered}
    if len(by_key) != len(ordered):
        duplicates = [k for k in by_key if sum(1 for i in ordered if i.key == k) > 1]
        raise ValueError(
            f"build_groups received the same key more than once: {sorted(duplicates)[:5]}. "
            "Identity is the database primary key; two rows for one id is a caller bug "
            "that would make the DI22 guarantee meaningless."
        )

    clusters = _Clusters()
    signatures: dict[ItemKey, tuple[int, ...]] = {}

    # -- tier 1: exact ------------------------------------------------------
    #
    # Hashes are computed whether or not the tier is enabled: P19's incremental
    # enrichment keys on them, and `exact_enabled: false` is about *grouping*,
    # not about refusing to know what a post's content hash is.
    buckets = group_exact(ordered)
    content_hashes = {item.key: hash_item(item) for item in ordered}
    if cfg.exact_enabled:
        for keys in buckets.values():
            if len(keys) > 1:
                clusters.open(METHOD_EXACT, keys, similarity=None)

    # -- tier 2: MinHash + LSH ---------------------------------------------
    if cfg.minhash_enabled:
        index = LshIndex(num_perm=cfg.num_perm, threshold=cfg.jaccard_threshold)
        # Every item is indexed, including one an exact group already claimed.
        # Indexing only the unclaimed would strand a post that is 95% similar to
        # a member of an exact group in a group of its own -- collapse rate lost
        # for no reason, and two groups describing one discussion.
        for item in ordered:
            sig = signature(shingles(_dedupe_text(item), cfg.shingle_k), cfg.num_perm)
            if sig is not None:
                signatures[item.key] = sig
                index.add(item.key, sig)

        for item in ordered:
            if clusters.holds(item.key):
                continue
            matches = []
            for candidate in sorted(index.candidates(item.key)):
                sim = index.similarity(item.key, candidate)
                # The band collision is recall; this comparison is the decision.
                if sim >= cfg.jaccard_threshold:
                    matches.append((candidate, sim))
            if not matches:
                continue
            # Best-first, so the greedy complete-linkage pass keeps the strongest
            # matches when it has to drop one.
            matches.sort(key=lambda m: (-m[1], m[0]))
            clusters.attach(
                METHOD_MINHASH,
                item.key,
                matches,
                similarity=index.similarity,
                threshold=cfg.jaccard_threshold,
            )

    # -- tier 3: semantic, optional and additive ----------------------------
    if cfg.semantic_threshold is not None:
        pairs = similar_pairs(
            [_dedupe_text(item) for item in ordered],
            cfg.semantic_threshold,
            encoder,
        )
        # Cosine scores, keyed both ways, so the complete-linkage check can ask
        # about any pair. A pair the encoder never scored above the threshold is
        # absent and reads as 0.0 -- which correctly refuses the join rather than
        # assuming similarity nobody measured.
        cosines = {(ordered[i].key, ordered[j].key): score for i, j, score in pairs}
        cosines.update({(b, a): s for (a, b), s in list(cosines.items())})

        for i, j, score in pairs:
            a, b = ordered[i].key, ordered[j].key
            if clusters.holds(a) and clusters.holds(b):
                continue
            new, existing = (a, b) if not clusters.holds(a) else (b, a)
            clusters.attach(
                METHOD_SEMANTIC,
                new,
                [(existing, score)],
                similarity=lambda x, y: cosines.get((x, y), 0.0),
                threshold=cfg.semantic_threshold,
            )

    groups = clusters.freeze(by_key)
    validate_membership(groups)

    # The reason follows how the MEMBER joined, not how its group is described.
    # `detail` carries the tier, which is P9's D3 shape: one counted reason so
    # GateReport's fixed key set survives, with the granularity AD-10b needs kept
    # underneath it.
    rejections: dict[ItemKey, RuleResult] = {}
    for group in groups:
        for key in group.duplicates:
            joined_by = clusters.joined_by(key)
            rejections[key] = duplicate(reason_for_method(joined_by), detail=joined_by)

    return CascadeResult(
        groups=tuple(groups),
        content_hashes=content_hashes,
        signatures=signatures,
        rejections=rejections,
    )


def _dedupe_text(item: DedupItem) -> str:
    """The text tiers 2 and 3 see: the **normalised** title and body, separated.

    ⚠️ Normalised, not raw, and the difference was measured rather than reasoned
    about. [06c §4.2](../../docs/06c-local-first-pipeline.md) chooses character
    n-grams *because* *"typos, punctuation, and casing vary far more than
    substance"* — that is a statement about what the tier must **absorb**, and
    shingling raw text does the opposite. Measured 2026-08-14: ``"Which CRM
    should I use for my small startup team?"`` against the same sentence
    casefolded and without the question mark estimated Jaccard **0.55** raw and
    **1.00** normalised. At a 0.85 threshold the raw form misses a pair that
    differs only in capitalisation, which is the single most common way a repost
    differs from its original.

    Normalising does **not** collapse tier 2 into tier 1. Tier 1 requires the
    normalised strings to be *equal*; tier 2 finds them ≥ 85% similar, which is
    a strictly larger set — and tier 1 has already removed the equal ones by the
    time this runs.

    An item with **no** text returns ``""``, not ``"\\n"``. The separator alone
    is one character, which :func:`~src.dedupe.minhash.shingles` would happily
    turn into a single shingle — giving every body-less post in a run the *same*
    signature and grouping them all together on the strength of a newline.
    """
    title, body = normalise(item.title), normalise(item.body)
    if not title and not body:
        return ""
    return f"{title}\n{body}"


def validate_membership(groups: Sequence[Group]) -> None:
    """DI22: no item may belong to two groups. Raises :class:`MembershipError`.

    Independent of :func:`build_groups`' ``claimed`` set on purpose. One is a
    construction that cannot produce the violation; this is a check that would
    catch it if some future caller built groups another way. A guarantee with
    only one of the two is a guarantee that stops holding the day someone adds a
    fourth tier.
    """
    seen: dict[ItemKey, int] = {}
    for index, group in enumerate(groups):
        for key in group.members:
            if key in seen:
                raise MembershipError(
                    f"{key} is claimed by group {seen[key]} ({groups[seen[key]].method}) "
                    f"and group {index} ({group.method}). dedup_members cannot express "
                    "this constraint -- it has no run_id -- so it is upheld here (DI22)."
                )
            seen[key] = index


def group_rows(
    result: CascadeResult,
    *,
    run_id: int | None = None,
    project_id: int | None = None,
    created_at: datetime | None = None,
) -> list[tuple[DedupGroup, list[DedupMember]]]:
    """Turn groups into unsaved ORM rows, paired with their members.

    Returned unsaved and paired rather than written here so the caller owns the
    transaction. **R8** makes the worker the sole bulk writer, and a function
    that opened its own session inside a library would take that decision away
    from it.

    ``created_at`` is injectable so a test can assert an exact value instead of
    asserting that *something* was written.
    """
    validate_membership(result.groups)
    out: list[tuple[DedupGroup, list[DedupMember]]] = []
    for group in result.groups:
        kind, row_id = group.representative
        row = DedupGroup(
            project_id=project_id,
            run_id=run_id,
            representative_lead_id=row_id if kind == KIND_LEAD else None,
            representative_comment_id=None if kind == KIND_LEAD else row_id,
            member_count=group.member_count,
            method=group.method,
            similarity=group.similarity,
        )
        if created_at is not None:
            row.created_at = created_at
        members = [
            DedupMember(
                lead_id=key[1] if key[0] == KIND_LEAD else None,
                comment_id=None if key[0] == KIND_LEAD else key[1],
                is_representative=(key == group.representative),
            )
            for key in group.members
        ]
        out.append((row, members))
    return out


def band_rows(
    result: CascadeResult,
    settings: DedupSettings | None = None,
    *,
    run_id: int | None = None,
    project_id: int | None = None,
) -> list[MinhashBand]:
    """Turn the run's signatures into ``minhash_bands`` rows.

    Written for the items the cascade signed, which is *"rebuilt per run, purged
    with the run"* — the ``MinhashBand`` docstring's own description, and why its
    ``run_id`` cascades on delete where ``dedup_groups.run_id`` sets null.

    Nothing reads these back yet: :class:`~src.dedupe.minhash.LshIndex` is
    in-memory and per run. They are written because
    [34 §P10](../../docs/34-implementation-plan.md) task 5's tables include the
    index, and because a cross-run index is P11's first cheap win once it has a
    ``project_id`` to scope by.
    """
    cfg = settings or DedupSettings()
    num_bands = LshIndex(num_perm=cfg.num_perm, threshold=cfg.jaccard_threshold).num_bands
    rows: list[MinhashBand] = []
    for key, sig in result.signatures.items():
        kind, row_id = key
        for band_index, band_hash in enumerate(bands(sig, num_bands)):
            rows.append(
                MinhashBand(
                    project_id=project_id,
                    run_id=run_id,
                    band_index=band_index,
                    band_hash=band_hash,
                    lead_id=row_id if kind == KIND_LEAD else None,
                    comment_id=None if kind == KIND_LEAD else row_id,
                )
            )
    return rows


def persist(
    session,
    result: CascadeResult,
    *,
    run_id: int | None = None,
    project_id: int | None = None,
    settings: DedupSettings | None = None,
    write_bands: bool = True,
) -> tuple[int, int]:
    """Write groups, members and bands. Returns ``(groups written, members written)``.

    Flushes after each group so that ``DedupMember.group_id`` has an id to point
    at; does **not** commit, because the caller owns the transaction boundary
    (R8, and the same shape every repository in ``src/db/repositories/`` uses).

    ⚠️ **This lives here rather than in ``src/db/repositories/``**, which is where
    every other writer in this project lives. That is not a preference:
    [34 §P10](../../docs/34-implementation-plan.md)'s **Files** row is
    ``src/dedupe/{__init__,exact,minhash,semantic,groups}.py`` and
    ``requirements.txt``, and [lock §3](../../docs/EXECUTION_MODE_LOCK.md) step 4
    is *"every file in the phase's Files row, and nothing outside it"*. A
    ``DedupRepository`` is the right long-term home and P11 — which adds
    ``src/db/repositories/comments.py`` and owns the first caller — is the phase
    that may create it.
    """
    validate_membership(result.groups)
    groups_written = 0
    members_written = 0
    for row, members in group_rows(result, run_id=run_id, project_id=project_id):
        session.add(row)
        session.flush()
        for member in members:
            member.group_id = row.id
            session.add(member)
        groups_written += 1
        members_written += len(members)

    if write_bands:
        for band in band_rows(result, settings, run_id=run_id, project_id=project_id):
            session.add(band)

    return groups_written, members_written
