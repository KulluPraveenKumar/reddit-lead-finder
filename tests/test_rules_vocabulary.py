"""P9's four and P10's two must stay a strict subset of P19's eleven.

This file is the one place in the project that may import **both** sides of the
R3 boundary, because it is a test and not production code. That is what lets the
agreement be asserted rather than hoped for: `src/rules/` spells its reasons to
match `src/ai/gate.py`'s `RejectionReason` and deliberately does not import it,
so without this test the two could drift apart by one typo and nothing would
notice until P19 rendered a counter key that was never counted.
"""

from __future__ import annotations

import pytest

from src.ai.gate import RejectionReason
from src.dedupe import DUPLICATE_EXACT, DUPLICATE_NEAR, DedupItem, DedupSettings, duplicate
from src.dedupe import REASONS as DEDUPE_REASONS
from src.dedupe.groups import build_groups
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


def test_p9_and_p10_together_reach_six_of_p19s_eleven():
    """The running total, asserted so the next phase inherits a number rather
    than recounting. The remaining five need comments (P11), a pre-score (P11),
    a response cache (P19/P20) or an ``ai_budgets`` row (``0009``, P19)."""
    combined = REASONS | DEDUPE_REASONS
    assert len(combined) == 6
    assert set(RejectionReason.ALL) - combined == {
        "already_analyzed",
        "out_of_window",
        "downvoted",
        "below_prescore",
        "budget_exhausted",
    }


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
