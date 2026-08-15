"""P9's four, P10's two and P11's two must stay a strict subset of P19's eleven.

This file is the one place in the project that may import **both** sides of the
R3 boundary, because it is a test and not production code. That is what lets the
agreement be asserted rather than hoped for: `src/rules/` spells its reasons to
match `src/ai/gate.py`'s `RejectionReason` and deliberately does not import it,
so without this test the two could drift apart by one typo and nothing would
notice until P19 rendered a counter key that was never counted.

**P11 raises the running total from six to eight** and adds a fourth vocabulary
to the comparison: `src/discovery/triage.py`'s nine reasons, which are live and
disagree with the rules' spelling. That is
[DI23](../docs/DEFERRED-IMPROVEMENTS.md), and P11 is the phase that must render
both on one page — so the display mapping is asserted here too, in the one file
allowed to see every side at once.
"""

from __future__ import annotations

import pytest

from src.ai.gate import RejectionReason
from src.dedupe import DUPLICATE_EXACT, DUPLICATE_NEAR, DedupItem, DedupSettings, duplicate
from src.dedupe import REASONS as DEDUPE_REASONS
from src.dedupe.groups import build_groups
from src.discovery.triage import REASONS as TRIAGE_REASONS
from src.rules import (
    BOT_OR_DELETED,
    NEGATIVE_TERM,
    REASONS,
    STRUCTURAL_NOISE,
    TOO_SHORT,
    RuleResult,
    reject,
)
from src.rules.authors import check_author
from src.rules.keywords import check_negative_terms
from src.rules.structural import check_length, check_structural
from src.scoring import BELOW_PRESCORE, OUT_OF_WINDOW, _reason
from src.scoring import REASONS as SCORING_REASONS
from src.scoring.funnel import TRIAGE_TO_GATE, to_gate_vocabulary


def test_p9_owns_exactly_four_reasons():
    """D2. Not eleven — seven of those need tables that do not exist until 0009."""
    expected = {NEGATIVE_TERM, STRUCTURAL_NOISE, TOO_SHORT, BOT_OR_DELETED}
    assert expected == REASONS
    assert len(REASONS) == 4


def test_every_p9_reason_is_one_of_p19s_eleven():
    """The subset claim D2 rests on, asserted rather than assumed.

    If this fails, one side was renamed and the other was not — and the symptom
    downstream is a funnel that under-reports by exactly the count nobody saw.
    """
    p19_vocabulary = set(RejectionReason.ALL)
    assert p19_vocabulary >= REASONS, (
        f"P9 invented a reason P19 does not count: {REASONS - p19_vocabulary}"
    )


def test_p9_does_not_claim_the_seven_reasons_it_cannot_produce():
    """The other seven belong to P10, P11 and P19. Naming one here would be a lie."""
    not_ours = set(RejectionReason.ALL) - REASONS
    assert not_ours == {
        "already_analyzed",
        "duplicate_exact",
        "duplicate_near",
        "out_of_window",
        "downvoted",
        "below_prescore",
        "budget_exhausted",
    }


# --------------------------------------------------------------------- P10
#
# P10 owns two more. They live in `src/dedupe/`, NOT in `src/rules/REASONS`,
# which is operator decision **D3**: PHASE-09-HANDOVER §3.3 asked for them to be
# added here, and `src/rules/__init__.py` is outside docs/34 §P10's Files row,
# which EXECUTION_MODE_LOCK §3 step 4 forbids editing. The subset claim is
# therefore asserted across both packages rather than within one.


def test_p10_owns_exactly_two_reasons():
    assert {DUPLICATE_EXACT, DUPLICATE_NEAR} == DEDUPE_REASONS
    assert len(DEDUPE_REASONS) == 2


def test_every_p10_reason_is_one_of_p19s_eleven():
    """The same claim as P9's, for the package that could not extend P9's set."""
    p19_vocabulary = set(RejectionReason.ALL)
    assert p19_vocabulary >= DEDUPE_REASONS, (
        f"P10 invented a reason P19 does not count: {DEDUPE_REASONS - p19_vocabulary}"
    )


def test_the_two_vocabularies_do_not_overlap():
    """Two packages owning one reason would make the funnel double-count it."""
    assert set() == REASONS & DEDUPE_REASONS


# --------------------------------------------------------------------- P11
#
# P11 owns two more, and they live in `src/scoring/` for the same reason P10's
# live in `src/dedupe/`: `src/rules/__init__.py` is outside docs/34 §P11's Files
# row. PHASE-10-HANDOVER §3.5 directs this explicitly — *"Follow P10's shape, not
# P9's instruction: declare them in `src/scoring/`, and extend this file's subset
# assertions from six to eight."*


def test_p11_owns_exactly_two_reasons():
    assert {BELOW_PRESCORE, OUT_OF_WINDOW} == SCORING_REASONS
    assert len(SCORING_REASONS) == 2


def test_every_p11_reason_is_one_of_p19s_eleven():
    """The same claim as P9's and P10's, for the third package inside the fence."""
    p19_vocabulary = set(RejectionReason.ALL)
    assert p19_vocabulary >= SCORING_REASONS, (
        f"P11 invented a reason P19 does not count: {SCORING_REASONS - p19_vocabulary}"
    )


def test_p11_does_not_claim_downvoted_even_though_it_ships_comments():
    """``downvoted`` is a comment with ``score < 0``, and P11 is the phase that
    first collects comments — so this is the reason P11 could most plausibly have
    taken, and deliberately does not.

    [PHASE-10-HANDOVER §3.5](../docs/PHASE-10-HANDOVER.md) fixes P11's two by
    name: *"Your reasons are ``below_prescore`` and ``out_of_window``."* P11
    stores comments but does not gate on them — nothing scores a comment until
    P19 composes the gate — and a reason claimed by a phase that never emits it
    is exactly the *"documented capability that does not exist"* trap, with the
    added cost that the eight-of-eleven count would be a lie.
    """
    assert "downvoted" not in SCORING_REASONS


def test_the_three_vocabularies_do_not_overlap():
    """Three packages, eight reasons, no reason owned twice.

    Overlap would make the funnel double-count: two modules would each increment
    the same key for different events, and the total would exceed ``collected``
    while every individual counter looked right.
    """
    assert set() == REASONS & DEDUPE_REASONS
    assert set() == REASONS & SCORING_REASONS
    assert set() == DEDUPE_REASONS & SCORING_REASONS


def test_p9_p10_and_p11_together_reach_eight_of_p19s_eleven():
    """The running total, asserted so the next phase inherits a number rather
    than recounting. Six at P10; **eight** now.

    The remaining three all need something no phase has yet built:
    ``already_analyzed`` needs the response cache (P19/P20), ``downvoted`` needs
    a comment-level gate (P19), and ``budget_exhausted`` needs an ``ai_budgets``
    row (``0009``, P19). All three are P19's, which is the first phase that can
    honestly claim eleven.
    """
    combined = REASONS | DEDUPE_REASONS | SCORING_REASONS
    assert len(combined) == 8
    assert set(RejectionReason.ALL) - combined == {
        "already_analyzed",
        "downvoted",
        "budget_exhausted",
    }


def test_p11_reject_refuses_a_reason_outside_its_vocabulary():
    """``src.rules.reject``'s guard, reproduced a second time — P10's precedent.

    Without it, the eight-are-a-subset-of-eleven claim above could be broken by a
    single call site inventing a ninth string, and the symptom would be a funnel
    key ``GateReport`` never renders.
    """
    with pytest.raises(ValueError, match="not one of the two reasons"):
        _reason("invented_reason", None)


def test_the_scoring_package_does_not_import_the_gate_it_agrees_with():
    """R3. ``RejectionReason`` contains both of P11's spellings already."""
    import src.scoring
    import src.scoring.features
    import src.scoring.funnel
    import src.scoring.holdout
    import src.scoring.prescore

    modules = (
        src.scoring,
        src.scoring.features,
        src.scoring.prescore,
        src.scoring.holdout,
        src.scoring.funnel,
    )
    for module in modules:
        leaked = [
            name
            for name in ("GateDecision", "GateReport", "RejectionReason", "PreAIGate")
            if hasattr(module, name)
        ]
        assert leaked == [], f"{module.__name__} has gate symbols in scope: {leaked}"


# ------------------------------------------------------- DI23, the two live
#
# P6's triage vocabulary and the rules vocabulary ship, disagree, and are both
# live from this phase. P11 renders both on one page, and reconciles them for
# DISPLAY ONLY — `src/scoring/funnel.py::TRIAGE_TO_GATE`. Neither writer changes.


def test_every_triage_reason_maps_onto_one_of_p19s_eleven():
    """DI23's reconciliation, asserted across all three vocabularies at once.

    This test is the reason ``TRIAGE_TO_GATE`` can be *"display only"* and still
    be trustworthy: an unmapped triage reason would reach the run page as a key
    the eleven-reason funnel never renders, which is the same silent
    under-reporting ``reject``'s guard prevents on the writing side.
    """
    p19_vocabulary = set(RejectionReason.ALL)
    unmapped = set(TRIAGE_REASONS) - set(TRIAGE_TO_GATE)
    assert unmapped == set(), f"triage reasons with no display mapping: {unmapped}"

    invented = set(TRIAGE_TO_GATE.values()) - p19_vocabulary
    assert invented == set(), f"TRIAGE_TO_GATE maps onto reasons P19 does not count: {invented}"


def test_the_mapping_covers_exactly_p6s_nine_and_invents_none():
    """Nine in, nine mapped. A tenth key would be a reason triage cannot produce."""
    assert set(TRIAGE_TO_GATE) == set(TRIAGE_REASONS)
    assert len(TRIAGE_REASONS) == 9


def test_the_five_structural_reasons_keep_their_granularity_as_detail():
    """P9's operator decision D3, applied to P6's data.

    *"5-12% structural noise"* is not something an operator can act on;
    *"8% megathread, 1% hiring"* is. Collapsing the five without keeping the name
    underneath would discard the only actionable half.
    """
    for reason in ("hiring", "giveaway", "megathread", "ama", "engagement_bait"):
        mapped, detail = to_gate_vocabulary(reason)
        assert mapped == "structural_noise"
        assert detail == reason


def test_an_unmapped_reason_passes_through_rather_than_being_dropped():
    """A reason nobody mapped must still be counted, under its own name.

    Dropping it would make the funnel under-report by exactly the amount nobody
    noticed — and the run page's headline check is that the counters *sum*.
    """
    mapped, detail = to_gate_vocabulary("some_future_reason")
    assert mapped == "some_future_reason"
    assert detail is None


def test_dedupe_reject_refuses_a_reason_outside_its_vocabulary():
    """Mutation M8 — ``src.rules.reject``'s guard, reproduced in the package that
    could not reuse it. Without it, D3's cost would be an unguarded call site."""
    with pytest.raises(ValueError, match="not one of the two reasons"):
        duplicate("duplicate_semantic")


def test_no_dedupe_call_site_returns_a_reason_outside_the_vocabulary():
    """Every rejecting path in the cascade, checked against the closed set."""
    body = "our spreadsheets are falling apart and we need a real crm for five people here"
    items = [
        DedupItem(("lead", 1), "Which CRM?", body, score=99),
        DedupItem(("lead", 2), "**Which CRM?**", body, score=5),
        DedupItem(("lead", 3), "Which CRM?", body.replace("five", "six"), score=5),
    ]
    rejections = build_groups(items, DedupSettings()).rejections
    assert rejections, "the fixture must produce at least one rejection"
    for result in rejections.values():
        assert result.rejected
        assert result.reason in DEDUPE_REASONS


def test_the_dedupe_package_does_not_import_the_gate_it_agrees_with():
    """R3. ``RejectionReason`` already contains both of P10's spellings, so
    importing them would look like good practice and breach the fence."""
    import src.dedupe
    import src.dedupe.exact
    import src.dedupe.groups
    import src.dedupe.minhash
    import src.dedupe.semantic

    modules = (
        src.dedupe,
        src.dedupe.exact,
        src.dedupe.minhash,
        src.dedupe.semantic,
        src.dedupe.groups,
    )
    for module in modules:
        leaked = [
            name
            for name in ("GateDecision", "GateReport", "RejectionReason", "PreAIGate")
            if hasattr(module, name)
        ]
        assert leaked == [], f"{module.__name__} has gate symbols in scope: {leaked}"


def test_reject_refuses_a_reason_outside_the_vocabulary():
    """Mutation M15 — a call site returning a twelfth string."""
    with pytest.raises(ValueError, match="not one of the four reasons"):
        reject("invented_reason")


@pytest.mark.parametrize(
    "result",
    [
        check_structural("Weekly megathread - ask your questions here"),
        check_negative_terms("this is spam", ["spam"]),
        check_length("tiny", 80),
        check_author("WikiTextBot"),
    ],
)
def test_no_call_site_returns_a_reason_outside_the_vocabulary(result: RuleResult):
    """Every rejecting path in the package, checked against the closed set."""
    assert result.rejected
    assert result.reason in REASONS


@pytest.mark.parametrize(
    "result",
    [
        check_structural("Looking for a tool to track competitor pricing"),
        check_negative_terms("a clean title", ["spam"]),
        check_length("x" * 200, 80),
        check_author("a_real_person"),
    ],
)
def test_an_admission_carries_no_reason_and_no_detail(result: RuleResult):
    assert not result.rejected
    assert result.reason is None
    assert result.detail is None


def test_the_rules_package_does_not_import_the_gate_it_agrees_with():
    """The agreement above is by spelling, not by import — R3.

    A reader seeing this file import both sides may conclude production code may
    too. It may not. `tests/test_boundaries.py` is the enforcement; this asserts
    the consequence at the place the temptation actually arises — that no gate
    symbol has arrived in a rules module's namespace by any route, including the
    `from src.ai.gate import *` spelling an AST import fence sees but a reader
    skimming for `GateDecision` might not.
    """
    import src.rules
    import src.rules.authors
    import src.rules.keywords
    import src.rules.structural

    modules = (src.rules, src.rules.keywords, src.rules.structural, src.rules.authors)
    for module in modules:
        leaked = [
            name
            for name in ("GateDecision", "GateReport", "RejectionReason", "PreAIGate")
            if hasattr(module, name)
        ]
        assert leaked == [], f"{module.__name__} has gate symbols in scope: {leaked}"
