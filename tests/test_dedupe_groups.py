"""The cascade — grouping, representative selection, DI22, and persistence.

Two things in this file are load-bearing beyond their own assertions:

* **DI22.** *"At most one group per run"* is not expressible in ``dedup_members``
  — no ``run_id``, and SQLite cannot constrain uniqueness across a join. P8
  deliberately shipped no test that appeared to check it and named P10 the owner.
  These are that test.
* **[06c §4.4] — group for analysis, score individually.** The whole cost saving
  is worthless if grouping also collapses the scores.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from src.dedupe import (
    DUPLICATE_EXACT,
    DUPLICATE_NEAR,
    METHOD_EXACT,
    METHOD_MINHASH,
    METHOD_SEMANTIC,
    DedupItem,
    DedupSettings,
    duplicate,
    reason_for_method,
)
from src.dedupe.groups import (
    CascadeResult,
    Group,
    MembershipError,
    band_rows,
    build_groups,
    choose_representative,
    group_rows,
    persist,
    validate_membership,
)

BODY = (
    "our spreadsheets are falling apart and we need a real crm tool for a team of "
    "five people. we have tried a few free options but none of them handle repeat "
    "customers properly and the reporting is useless. budget is tight but we can "
    "pay something monthly if it actually saves us time every week."
)


def item(row_id: int, title: str = "Which CRM?", body: str = BODY, **kw) -> DedupItem:
    return DedupItem(key=("lead", row_id), title=title, body=body, **kw)


# --------------------------------------------------- choose_representative


def test_the_representative_is_the_highest_ranked():
    """P11's pre-score wins when it is present — operator decision **D1**."""
    items = [item(1, rank=10.0, score=1), item(2, rank=90.0, score=1), item(3, rank=50.0)]
    assert choose_representative(items).key == ("lead", 2)


def test_without_a_rank_the_highest_score_wins():
    """The P10 fallback. ``src/scoring/prescore.py`` is P11's Files row and P11
    depends on P10, so there is no pre-score to rank by yet."""
    items = [item(1, score=3), item(2, score=91), item(3, score=44)]
    assert choose_representative(items).key == ("lead", 2)


def test_with_equal_scores_the_newest_wins():
    older = item(1, score=5, created_utc=datetime(2026, 1, 1, tzinfo=UTC))
    newer = item(2, score=5, created_utc=datetime(2026, 8, 1, tzinfo=UTC))
    assert choose_representative([older, newer]).key == ("lead", 2)


def test_a_missing_score_loses_to_any_score_including_a_negative_one():
    """``None`` is *unknown*, not *zero*, and Reddit scores go negative.

    The **negative** case is the one that distinguishes the two readings, and the
    original version of this test used ``0`` — where an unknown treated as ``0.0``
    ties and the row-id tie-break happens to produce the same answer. Mutation
    **M23** survived on exactly that, which is P9's **T5**: the survivor was a
    test defect, not a code defect.
    """
    assert choose_representative([item(1, score=None), item(2, score=0)]).key == ("lead", 2)
    assert choose_representative([item(1, score=None), item(2, score=-5)]).key == ("lead", 2)
    assert choose_representative([item(2, score=-5), item(1, score=None)]).key == ("lead", 2)


def test_a_naive_and_an_aware_datetime_do_not_raise():
    """Comparing ``datetime`` objects directly raises ``TypeError`` on a mixed
    corpus, and the one thing representative selection must never do is fail the
    run over a timezone."""
    naive = item(1, score=5, created_utc=datetime(2026, 1, 1))
    aware = item(2, score=5, created_utc=datetime(2026, 8, 1, tzinfo=UTC))
    assert choose_representative([naive, aware]).key in {("lead", 1), ("lead", 2)}


def test_selection_is_deterministic_when_everything_ties():
    """Without the ``row_id`` tie-break, ordering would depend on iteration
    order — and the identical-lead-set criterion would be unverifiable."""
    items = [item(3), item(1), item(2)]
    first = choose_representative(items).key
    for _ in range(20):
        assert choose_representative(list(reversed(items))).key == first


def test_an_empty_group_has_no_representative():
    with pytest.raises(ValueError, match="at least one member"):
        choose_representative([])


# ------------------------------------------------------------ the tiers


def test_tier_one_groups_an_exact_repost():
    items = [item(1), item(2, title="**Which CRM?**", body=BODY + "\n\nEDIT: solved")]
    result = build_groups(items)
    assert len(result.groups) == 1
    assert result.groups[0].method == METHOD_EXACT
    assert result.groups[0].similarity is None, "identical is not *similar*; it is not measured"


def test_tier_two_groups_a_near_duplicate():
    items = [item(1), item(2, body=BODY.replace("five people", "six people"))]
    result = build_groups(items)
    assert len(result.groups) == 1
    assert result.groups[0].method == METHOD_MINHASH
    assert result.groups[0].similarity >= 0.85


def test_an_unrelated_post_is_left_alone():
    items = [item(1), item(2), item(3, title="Best pizza in Chicago", body="Deep dish only.")]
    result = build_groups(items)
    assert ("lead", 3) not in result.grouped_keys


def test_a_later_tier_extends_a_group_rather_than_opening_a_second():
    """Two groups over one discussion would show the operator a *"similar
    discussions"* panel that disagrees with itself depending on which lead they
    arrived from — and would cost a second enrichment for the same content."""
    items = [
        item(1),
        item(2, title="**Which CRM?**"),  # exact duplicate of 1
        item(3, body=BODY.replace("five people", "six people")),  # near-duplicate of 1
    ]
    result = build_groups(items)
    assert len(result.groups) == 1
    assert set(result.groups[0].members) == {("lead", 1), ("lead", 2), ("lead", 3)}


def test_an_extended_group_is_described_by_its_loosest_evidence():
    """``dedup_groups.method`` is the claim the operator is asked to trust.
    Calling an extended group *exact* would say its members are identical when
    one of them is merely 0.87 similar."""
    items = [item(1), item(2, title="**Which CRM?**"), item(3, body=BODY.replace("five", "six"))]
    assert build_groups(items).groups[0].method == METHOD_MINHASH


def test_a_member_reports_how_it_joined_not_how_its_group_is_described():
    """An exact duplicate inside an upgraded group is still an exact duplicate.

    Reporting every member as ``duplicate_near`` would move real
    ``duplicate_exact`` volume into the near bucket, and the two have very
    different implications: exact duplicates are reposts, near ones are separate
    conversations worth reading.
    """
    # Scores are explicit so lead 1 is unambiguously the representative -- with
    # all three unscored the tie-break picks the highest row id, and the item
    # under test would be the one nothing rejects.
    items = [
        item(1, score=99),
        item(2, title="**Which CRM?**", score=5),
        item(3, body=BODY.replace("five people", "six people"), score=5),
    ]
    result = build_groups(items)
    assert result.groups[0].representative == ("lead", 1)
    reasons = {k: r.reason for k, r in result.rejections.items()}
    assert reasons[("lead", 2)] == DUPLICATE_EXACT
    assert reasons[("lead", 3)] == DUPLICATE_NEAR


def test_the_representative_is_never_rejected():
    items = [item(1, score=1), item(2, title="**Which CRM?**", score=99)]
    result = build_groups(items)
    assert result.groups[0].representative == ("lead", 2)
    assert ("lead", 2) not in result.rejections
    assert ("lead", 1) in result.rejections


def test_content_hashes_are_returned_for_ungrouped_items_too():
    """P19's incremental enrichment keys on ``(content_hash, prompt_version)``."""
    items = [item(1), item(2, title="Unrelated", body="Nothing alike at all here.")]
    result = build_groups(items)
    assert set(result.content_hashes) == {("lead", 1), ("lead", 2)}


def test_hashes_are_computed_even_when_the_exact_tier_is_off():
    """``exact_enabled: false`` is about *grouping*, not about refusing to know
    what a post's content hash is."""
    result = build_groups([item(1)], DedupSettings(exact_enabled=False))
    assert result.content_hashes[("lead", 1)]


def test_an_empty_run_groups_nothing_and_does_not_divide_by_zero():
    result = build_groups([])
    assert result.groups == ()
    assert result.collapse_rate(0) == 0.0


def test_a_single_item_is_not_a_group():
    assert build_groups([item(1)]).groups == ()


def test_a_repeated_key_is_a_caller_bug_not_a_group():
    """Identity is the database primary key. Two rows for one id would make the
    DI22 guarantee meaningless."""
    with pytest.raises(ValueError, match="same key more than once"):
        build_groups([item(1), item(1)])


def test_two_empty_items_group_with_each_other_and_with_nothing_else():
    """Boundary, and the one that would be dangerous to get wrong.

    Two body-less posts genuinely *are* identical, so tier 1 grouping them is
    correct. What must not happen is an empty post being pulled into a **real**
    discussion's group — the failure mode a sentinel-filled signature would cause,
    which is why :func:`~src.dedupe.minhash.signature` returns ``None`` for a
    shingle-less input.
    """
    items = [DedupItem(("lead", 1), "", ""), DedupItem(("lead", 2), "", ""), item(3)]
    result = build_groups(items, DedupSettings(minhash_enabled=True))

    assert len(result.groups) == 1
    assert result.groups[0].method == METHOD_EXACT
    assert set(result.groups[0].members) == {("lead", 1), ("lead", 2)}
    assert ("lead", 3) not in result.grouped_keys

    # And neither empty item was signed at all -- `_dedupe_text` returns "" for a
    # text-less item rather than the bare "\n" separator, which would otherwise
    # become one shingle and give every body-less post in a run one signature.
    assert ("lead", 1) not in result.signatures
    assert ("lead", 2) not in result.signatures
    assert ("lead", 3) in result.signatures


def test_a_shingle_less_item_gets_no_signature_and_joins_nothing():
    """The narrower claim, on the function that owns it."""
    from src.dedupe.minhash import shingles, signature

    assert signature(shingles(""), 128) is None


# ------------------------------------------------------------- rollbacks


def test_minhash_disabled_is_the_documented_rollback():
    """``dedup.minhash_enabled: false``. Executed, not merely documented."""
    items = [item(1), item(2, body=BODY.replace("five people", "six people"))]
    assert build_groups(items, DedupSettings(minhash_enabled=True)).groups
    assert build_groups(items, DedupSettings(minhash_enabled=False)).groups == ()


def test_switching_a_tier_off_only_ever_produces_more_singletons():
    """What makes these rollbacks rather than behaviour changes: no item leaves
    the run and no group is re-formed differently — groups only fail to form."""
    items = [
        item(1),
        item(2, title="**Which CRM?**"),
        item(3, body=BODY.replace("five people", "six people")),
        item(4, title="Pizza", body="Deep dish only."),
    ]
    universe = {i.key for i in items}
    full = build_groups(items, DedupSettings())
    reduced = build_groups(items, DedupSettings(minhash_enabled=False))
    none = build_groups(items, DedupSettings(exact_enabled=False, minhash_enabled=False))

    assert reduced.grouped_keys <= full.grouped_keys
    assert none.grouped_keys <= reduced.grouped_keys
    for result in (full, reduced, none):
        assert result.content_hashes.keys() == universe


# ------------------------------------- complete linkage, and the threshold
#
# These exist because mutation M35 -- replacing the cascade's
# `sim >= jaccard_threshold` with `sim >= 0.0` -- SURVIVED the first full run.
# Probing why found a real defect rather than a mere test gap, so the test below
# is a regression test as much as a mutation kill.


def _graded_corpus(n: int = 30) -> list[DedupItem]:
    """One post, then n increasingly divergent rewrites of it.

    A graded corpus is what exposes chaining: a run of items each near its
    neighbour and far from the far end is exactly the shape single linkage
    collapses into one group.
    """
    words = BODY.split()
    items = []
    for step in range(n):
        rewritten = words[:]
        for i in range(step):
            rewritten[(i * 3) % len(rewritten)] = f"zz{i}"
        items.append(DedupItem(("lead", step + 1), "which crm", " ".join(rewritten)))
    return items


def _index_for(items):
    from src.dedupe.groups import _dedupe_text
    from src.dedupe.minhash import LshIndex, shingles, signature

    index = LshIndex()
    for it in items:
        index.add(it.key, signature(shingles(_dedupe_text(it))))
    return index


def test_no_group_contains_a_pair_below_the_threshold():
    """**Complete linkage** — and the defect mutation testing found.

    The single-linkage version of ``_Clusters.attach`` joined a cluster on the
    strength of **one** match, so ``A~B`` at 0.90 and ``B~C`` at 0.90 put ``A``
    and ``C`` in one group at **0.445** — measured on this corpus, 2026-08-14, in
    a 14-member group. Those two leads would then have **shared one AI
    analysis**, which is the silent quality regression
    [06c §4.4] exists to forbid, and
    [06c §4.2] asks for *pairs above a threshold*, not connected components.

    Every pair, not every member against the representative: the representative
    is chosen after the fact, so checking only against it would leave the same
    chaining unmeasured between two ordinary members.
    """
    items = _graded_corpus()
    result = build_groups(items, DedupSettings())
    index = _index_for(items)

    assert result.groups, "the corpus must produce groups or this asserts nothing"
    for group in result.groups:
        if group.method != METHOD_MINHASH:
            continue
        members = group.members
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                similarity = index.similarity(members[i], members[j])
                assert similarity >= 0.85, (
                    f"{members[i]} and {members[j]} share a group at {similarity:.3f}, "
                    "below the 0.85 threshold -- single-linkage chaining"
                )


def test_banding_offers_below_threshold_candidates_that_the_cascade_refuses():
    """The cascade's threshold check is load-bearing, and this proves it runs.

    Banding is a **recall** device: on this corpus it offers pairs that are only
    0.4-0.8 similar. If ``build_groups`` did not compare, they would group. This
    is what mutation M35 attacks.
    """
    items = _graded_corpus()
    index = _index_for(items)

    offered_below = {
        tuple(sorted((a.key, candidate)))
        for a in items
        for candidate in index.candidates(a.key)
        if index.similarity(a.key, candidate) < 0.85
    }
    assert offered_below, "the fixture must offer below-threshold candidates"

    result = build_groups(items, DedupSettings())
    grouped_pairs = {
        tuple(sorted((m1, m2)))
        for g in result.groups
        for m1 in g.members
        for m2 in g.members
        if m1 != m2
    }
    assert offered_below & grouped_pairs == set(), (
        "a pair banding offered below the threshold was grouped anyway"
    )


#: A fixed similarity table for the linkage tests below. The anchor reaches both
#: matches; the two matches do not reach each other.
_LINKAGE = {
    (("lead", 1), ("lead", 2)): 0.91,
    (("lead", 1), ("lead", 3)): 0.88,
    (("lead", 2), ("lead", 3)): 0.79,
}


def _fixed_similarity(a, b):
    return _LINKAGE.get((a, b)) or _LINKAGE.get((b, a), 0.0)


def test_a_new_cluster_is_also_built_by_complete_linkage():
    """Opening a cluster obeys the same rule as joining one.

    ⚠️ **Driven by a fixed similarity table, not by a corpus, and that is the
    point.** The first version of this test built three documents and let the LSH
    index find them — and it **failed on correct code**, because banding is
    *probabilistic*: a 0.906 pair shares a band only ~83% of the time across 8
    bands of 16 rows, so the anchor did not reliably see both matches. A test
    whose fixture is a coin flip cannot distinguish single from complete linkage;
    worse, while it was red it made **every** mutation look detected, including a
    deliberate no-op control. Caught because that control was in the set.

    The corpus-level property is still asserted — by
    :func:`test_no_group_contains_a_pair_below_the_threshold`, which holds
    whichever pairs banding happens to offer.
    """
    from src.dedupe.groups import _Clusters

    clusters = _Clusters()
    clusters.attach(
        METHOD_MINHASH,
        ("lead", 1),
        [(("lead", 2), 0.91), (("lead", 3), 0.88)],
        similarity=_fixed_similarity,
        threshold=0.85,
    )
    groups = clusters.freeze({("lead", n): item(n) for n in (1, 2, 3)})

    assert len(groups) == 1
    assert groups[0].member_count == 2, (
        "all three grouped means the anchor's two matches were admitted without "
        "being compared to each other -- single linkage"
    )
    assert set(groups[0].members) == {("lead", 1), ("lead", 2)}, "the stronger match wins"


def test_joining_a_cluster_obeys_complete_linkage_too():
    """The other branch: an existing cluster refuses a key it does not fully reach."""
    from src.dedupe.groups import _Clusters

    clusters = _Clusters()
    clusters.open(METHOD_MINHASH, [("lead", 1), ("lead", 2)], similarity=0.91)
    clusters.attach(
        METHOD_MINHASH,
        ("lead", 3),
        [(("lead", 1), 0.88)],
        similarity=_fixed_similarity,
        threshold=0.85,
    )

    assert not clusters.holds(("lead", 3)), (
        "lead 3 reaches lead 1 at 0.88 but lead 2 only at 0.79; admitting it would "
        "put a 0.79 pair in one group"
    )


def test_complete_linkage_admits_a_key_that_reaches_every_member():
    """The other side — the guard must not refuse everything."""
    from src.dedupe.groups import _Clusters

    clusters = _Clusters()
    clusters.open(METHOD_MINHASH, [("lead", 1), ("lead", 2)], similarity=0.91)
    clusters.attach(
        METHOD_MINHASH,
        ("lead", 4),
        [(("lead", 1), 0.95)],
        similarity=lambda a, b: 0.95,
        threshold=0.85,
    )
    assert clusters.holds(("lead", 4))


def test_a_chain_of_near_duplicates_does_not_become_one_group():
    """The shape of the defect, stated as small and readable as it can be."""
    items = _graded_corpus(20)
    result = build_groups(items, DedupSettings())
    biggest = max((g.member_count for g in result.groups), default=0)
    assert biggest < len(items), (
        f"a {biggest}-member group over {len(items)} graded variants is transitive closure, "
        "not near-duplicate grouping"
    )


# ----------------------------------------------------------- DI22


def test_no_item_belongs_to_two_groups():
    """DI22, over a corpus built to provoke it: an exact pair, a near-duplicate
    of one of them, and a near-duplicate of the near-duplicate."""
    items = [
        item(1),
        item(2, title="**Which CRM?**"),
        item(3, body=BODY.replace("five people", "six people")),
        item(4, body=BODY.replace("five people", "seven people")),
    ]
    result = build_groups(items)
    validate_membership(result.groups)

    seen: set = set()
    for group in result.groups:
        for key in group.members:
            assert key not in seen, f"{key} is in two groups"
            seen.add(key)


def test_validate_membership_catches_a_hand_built_violation():
    """The construction in ``build_groups`` cannot produce this; the check must
    still exist, or the guarantee stops holding the day someone adds a fourth
    tier."""
    a = Group(METHOD_EXACT, ("lead", 1), (("lead", 1), ("lead", 2)))
    b = Group(METHOD_MINHASH, ("lead", 2), (("lead", 2), ("lead", 3)))
    with pytest.raises(MembershipError, match="claimed by group 0"):
        validate_membership([a, b])


def test_persistence_refuses_a_result_that_violates_di22():
    """A caller that built groups some other way must not be able to write them."""
    bad = CascadeResult(
        groups=(
            Group(METHOD_EXACT, ("lead", 1), (("lead", 1), ("lead", 2))),
            Group(METHOD_MINHASH, ("lead", 2), (("lead", 2), ("lead", 3))),
        )
    )
    with pytest.raises(MembershipError):
        group_rows(bad)


def test_a_representative_must_be_one_of_its_own_members():
    """Otherwise ``dedup_groups.representative_lead_id`` points outside the group
    it heads, and the shared analysis is linked to a lead nobody grouped."""
    with pytest.raises(ValueError, match="not among its own members"):
        Group(METHOD_EXACT, ("lead", 9), (("lead", 1), ("lead", 2)))


def test_tier_three_cannot_steal_a_member_from_an_earlier_tier():
    """The DI22 arm most likely to break: tier 3 sees the whole corpus, so it
    must consult the claim state before it groups."""

    class GreedyEncoder:
        def encode(self, texts):
            return [[1.0, 0.0]] * len(texts)  # everything is identical

    items = [item(1), item(2, title="**Which CRM?**"), item(3, title="Pizza", body="Deep dish.")]
    result = build_groups(items, DedupSettings(semantic_threshold=0.5), encoder=GreedyEncoder())
    validate_membership(result.groups)


# ------------------------------------------- group for analysis, score apart


def test_grouping_mutates_no_per_item_score():
    """[06c §4.4]. Emitting one score for a group of three would give the
    operator three identical numbers for three different-value leads, and they
    would correctly stop trusting the ranking."""
    items = [item(1, score=10, rank=5.0), item(2, title="**Which CRM?**", score=3, rank=1.0)]
    before = [(i.key, i.score, i.rank) for i in items]
    build_groups(items)
    assert [(i.key, i.score, i.rank) for i in items] == before


def test_a_group_of_n_keeps_n_members_and_n_identities():
    """P10's checkable half of *"a group of N yields N distinct pre-scores"* —
    operator decision **D1**. The pre-scores themselves are P11's, because
    ``src/scoring/prescore.py`` does not exist until then; what P10 must prove is
    that grouping preserves N distinct items to carry them."""
    items = [
        item(1, score=1),
        item(2, title="**Which CRM?**", score=2),
        item(3, title="*Which CRM?*", score=3),
    ]
    result = build_groups(items)
    group = result.groups[0]
    assert group.member_count == 3
    assert len(set(group.members)) == 3
    assert len({i.score for i in items}) == 3, "the three items still carry three distinct scores"


def test_the_dedup_package_never_reads_a_score_field_it_did_not_receive():
    """``rank`` and ``score`` are inputs. Nothing here derives, stores or updates
    ``leads.confidence_score`` — that column is P21's."""
    result = build_groups([item(1), item(2, title="**Which CRM?**")])
    assert not hasattr(result, "confidence_score")
    assert not hasattr(result.groups[0], "confidence_score")


# ------------------------------------------------------------- collapse


def test_collapse_rate_counts_items_removed_from_enrichment():
    items = [item(1), item(2, title="**Which CRM?**"), item(3, title="Pizza", body="Deep dish.")]
    result = build_groups(items)
    assert result.collapse_rate(len(items)) == pytest.approx(1 / 3)


def test_collapse_rate_of_an_empty_run_is_zero():
    assert CascadeResult().collapse_rate(0) == 0.0
    assert CascadeResult().collapse_rate(-1) == 0.0


# ------------------------------------------------------------- rows


def test_group_rows_map_a_lead_representative_to_the_lead_column():
    result = build_groups([item(1, score=99), item(2, title="**Which CRM?**", score=1)])
    ((row, members),) = group_rows(result, run_id=7, project_id=None)
    assert row.representative_lead_id == 1
    assert row.representative_comment_id is None
    assert row.run_id == 7
    assert row.member_count == 2
    assert row.method == METHOD_EXACT
    assert sum(1 for m in members if m.is_representative) == 1


def test_group_rows_map_a_comment_representative_to_the_comment_column():
    """``ck_dedup_members_one_target`` allows exactly one of the two."""
    items = [
        DedupItem(("comment", 1), "Which CRM?", BODY, score=99),
        DedupItem(("comment", 2), "**Which CRM?**", BODY, score=1),
    ]
    result = build_groups(items)
    ((row, members),) = group_rows(result)
    assert row.representative_comment_id == 1
    assert row.representative_lead_id is None
    for member in members:
        assert (member.lead_id is None) != (member.comment_id is None)


def test_created_at_is_injectable_so_a_test_can_assert_a_value():
    stamp = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    result = build_groups([item(1), item(2, title="**Which CRM?**")])
    ((row, _),) = group_rows(result, created_at=stamp)
    assert row.created_at == stamp


def test_band_rows_cover_every_signature_and_every_band():
    items = [item(1), item(2, body=BODY.replace("five people", "six people"))]
    result = build_groups(items)
    rows = band_rows(result, DedupSettings(), run_id=3)
    assert len(rows) == len(result.signatures) * 8
    assert {r.band_index for r in rows} == set(range(8))
    assert all(r.run_id == 3 for r in rows)
    assert all(len(r.band_hash) <= 32 for r in rows)


def test_an_item_key_must_be_a_lead_or_a_comment():
    with pytest.raises(ValueError, match="lead or a comment"):
        DedupItem(("subreddit", 1), "t", "b")


# ------------------------------------------------------------- persist


def _seed_leads(session, row_ids):
    """Real ``leads`` rows for the foreign keys to point at.

    ``dedup_members.lead_id`` carries ``REFERENCES leads(id) ON DELETE CASCADE``,
    so writing a member for a lead that does not exist raises ``FOREIGN KEY
    constraint failed``. Seeding is not scaffolding — it is what makes these
    tests exercise the real constraint rather than an unconstrained table.
    """
    from src.db.models import Lead

    for row_id in row_ids:
        session.add(
            Lead(
                id=row_id,
                reddit_id=f"t3_test{row_id}",
                subreddit="testsub",
                author="someone",
                title="Which CRM?",
                url=f"https://www.reddit.com/r/testsub/comments/test{row_id}/",
                created_utc=datetime(2026, 8, 14, tzinfo=UTC),
            )
        )
    session.flush()


def test_persist_writes_groups_members_and_bands(temp_db):
    from src.db.database import session_scope
    from src.db.models import DedupGroup, DedupMember, MinhashBand

    items = [item(1, score=9), item(2, title="**Which CRM?**", score=1)]
    result = build_groups(items)

    with session_scope() as session:
        _seed_leads(session, [1, 2])
        groups, members = persist(session, result, run_id=None)
        session.commit()
        assert (groups, members) == (1, 2)

    with session_scope() as session:
        assert session.query(DedupGroup).count() == 1
        assert session.query(DedupMember).count() == 2
        assert session.query(MinhashBand).count() == len(result.signatures) * 8
        stored = session.query(DedupGroup).one()
        assert stored.method == METHOD_EXACT
        assert stored.member_count == 2
        assert [m.group_id for m in session.query(DedupMember).all()] == [stored.id, stored.id]


def test_persist_can_skip_the_band_index(temp_db):
    from src.db.database import session_scope
    from src.db.models import MinhashBand

    result = build_groups([item(1), item(2, title="**Which CRM?**")])
    with session_scope() as session:
        _seed_leads(session, [1, 2])
        persist(session, result, write_bands=False)
        session.commit()
    with session_scope() as session:
        assert session.query(MinhashBand).count() == 0


def test_persist_writes_nothing_for_a_run_with_no_groups(temp_db):
    from src.db.database import session_scope
    from src.db.models import DedupGroup

    result = build_groups([item(1), item(2, title="Pizza", body="Deep dish only.")])
    with session_scope() as session:
        assert persist(session, result, write_bands=False) == (0, 0)
        session.commit()
    with session_scope() as session:
        assert session.query(DedupGroup).count() == 0


def test_the_within_group_unique_index_still_holds(temp_db):
    """What ``0006`` *does* enforce, as opposed to DI22's inexpressible claim.

    Asserted so the two are not confused: a reader who sees only the DI22 tests
    might conclude the schema enforces nothing.
    """
    from sqlalchemy.exc import IntegrityError

    from src.db.database import session_scope
    from src.db.models import DedupGroup, DedupMember

    with session_scope() as session:
        _seed_leads(session, [1])
        group = DedupGroup(member_count=1, method=METHOD_EXACT)
        session.add(group)
        session.flush()
        session.add(DedupMember(group_id=group.id, lead_id=1))
        session.flush()

        # Flushed one at a time, and the assertion is on the FLUSH. Adding both
        # and asserting on `commit` catches a PendingRollbackError instead: the
        # IntegrityError fires during an earlier autoflush and the commit only
        # reports that the transaction is already dead.
        session.add(DedupMember(group_id=group.id, lead_id=1))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


# ------------------------------------------------------------ vocabulary


def test_duplicate_refuses_a_reason_outside_the_two_p10_owns():
    """Mutation M8 — ``src.rules.reject``'s guard, reproduced because that
    function validates against P9's four and would refuse both of P10's."""
    with pytest.raises(ValueError, match="not one of the two reasons"):
        duplicate("duplicate_semantic")


def test_reason_for_method_covers_every_method_and_nothing_else():
    assert reason_for_method(METHOD_EXACT) == DUPLICATE_EXACT
    assert reason_for_method(METHOD_MINHASH) == DUPLICATE_NEAR
    assert reason_for_method(METHOD_SEMANTIC) == DUPLICATE_NEAR
    with pytest.raises(ValueError, match="is not one of"):
        reason_for_method("telepathy")


def test_a_semantic_duplicate_is_reported_as_near_not_as_a_twelfth_reason():
    """P19's vocabulary has no ``duplicate_semantic``. The tier is not lost — it
    is ``DedupGroup.method``, and it reaches the reason as ``detail``."""
    result = duplicate(reason_for_method(METHOD_SEMANTIC), detail=METHOD_SEMANTIC)
    assert result.reason == DUPLICATE_NEAR
    assert result.detail == METHOD_SEMANTIC


# ------------------------------------- the defensive paths, tested directly
#
# `build_groups` is constructed so that these cannot happen. They are still
# reachable by a future caller -- a fourth tier, a different driver -- and P9's
# T5 is the reason they are tested rather than trusted: a survivor can be a
# *test* defect, and an untested guard is a guard nobody has run.


def test_a_cluster_refuses_to_claim_a_key_it_already_holds():
    """``_Clusters.attach`` on an already-claimed key. The DI22 guarantee's
    innermost check: if this ever silently re-claimed, two groups would form."""
    from src.dedupe.groups import _Clusters

    clusters = _Clusters()
    clusters.open(METHOD_EXACT, [("lead", 1), ("lead", 2)], similarity=None)
    clusters.attach(METHOD_MINHASH, ("lead", 1), [(("lead", 3), 0.9)])

    assert clusters.holds(("lead", 1))
    assert not clusters.holds(("lead", 3)), "an already-claimed key must pull in nothing"


def test_a_match_list_with_nothing_new_opens_no_cluster():
    """``attach`` where every match is already claimed elsewhere and the key
    would be alone. A one-member group is not a group."""
    from src.dedupe.groups import _Clusters

    clusters = _Clusters()
    clusters.open(METHOD_EXACT, [("lead", 2), ("lead", 3)], similarity=None)
    # ("lead", 9) matches only keys held by another cluster, and the best of them
    # is in that cluster -- so it joins rather than opening a second one.
    clusters.attach(METHOD_MINHASH, ("lead", 9), [(("lead", 2), 0.9)])
    assert clusters.holds(("lead", 9))

    fresh = _Clusters()
    fresh.attach(METHOD_MINHASH, ("lead", 1), [])
    assert fresh.freeze({}) == []


def test_freeze_drops_a_cluster_that_lost_its_second_member():
    from src.dedupe.groups import _Clusters

    clusters = _Clusters()
    clusters.open(METHOD_EXACT, [("lead", 1)], similarity=None)
    assert clusters.freeze({("lead", 1): item(1)}) == []


def test_an_undateable_timestamp_does_not_raise():
    """``datetime.min.timestamp()`` raises on Windows rather than returning a
    negative epoch, and representative selection must never fail the run."""
    from src.dedupe.groups import _timestamp

    assert _timestamp(datetime.min) == float("-inf")
    assert _timestamp(None) == float("-inf")


def test_densification_terminates_when_there_is_nothing_to_borrow():
    """The unreachable arm of ``_densify``: every slot empty.

    ``signature`` returns ``None`` before calling it in that case, so this cannot
    happen through the public API. It is asserted anyway because the loop's exit
    path is the one that would spin if a future change removed the ``None``
    guard.
    """
    from src.dedupe.minhash import EMPTY, _densify

    slots = [EMPTY] * 8
    _densify(slots, 8)
    assert slots == [EMPTY] * 8


def test_the_result_exposes_its_representatives():
    """What P19 will iterate: the items that actually get enriched."""
    result = build_groups([item(1, score=99), item(2, title="**Which CRM?**", score=1)])
    assert result.representatives == (("lead", 1),)


def test_an_item_knows_whether_it_is_a_lead_or_a_comment():
    assert item(1).kind == "lead"
    assert item(1).row_id == 1
    assert DedupItem(("comment", 4), "t", "b").kind == "comment"


def test_dedup_items_are_immutable():
    """``replace`` works; assignment does not. Grouping must not be able to edit
    the corpus it was handed."""
    original = item(1, score=5)
    assert replace(original, score=6).score == 6
    with pytest.raises(FrozenInstanceError):
        original.score = 6  # type: ignore[misc]
