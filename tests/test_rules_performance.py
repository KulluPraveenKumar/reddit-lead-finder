"""Acceptance A6 — *"Rule evaluation < 1 ms/item"*, plus the sensitivity it lacks.

**Two assertions, because one is not enough and neither can replace the other.**

The published budget is 1 ms/item. Measured on an 8-core machine, 2026-08-14,
2000 items per batch:

===========================  ==================  ==============
Condition                    worst per item      vs 1 ms
===========================  ==================  ==============
quiet, wall clock            0.0101 ms           x99 headroom
quiet, CPU time              0.0156 ms           x64 headroom
12 busy processes, wall      0.0799 ms           x13 headroom
===========================  ==================  ==============

So an **absolute** budget is safe here in a way it never was for the feed parser
(DI18), and the difference is the headroom: the parser had ~2x, these rules have
13x even under twelve competing CPU-bound processes. No plausible machine load
crosses that, so :func:`test_rule_evaluation_stays_inside_the_budget` will not
flake and the published figure is asserted unchanged.

**But 100x headroom means 100x blindness.** At 0.0156 ms/item, the first
regression that budget would catch is roughly **64x** — which is not a
performance test, it is a smoke test. That is the same defect DI18 turned out to
be, arriving from the opposite direction: there the budget was too tight to
survive, here it is too loose to bite.

So :func:`test_rule_evaluation_cost_has_not_drifted` adds the ratio guard, using
the technique proved on the parser in this same phase. It catches a **3x**
regression reliably, which is a twentyfold improvement in sensitivity over the
budget alone.

⚠️ **A 2x regression is NOT reliably caught, and that is stated rather than
implied.** Measured separation is too narrow to place a threshold safely: worst
normal ratio 0.258, cheapest 2x regression 0.326 — 1.26x apart in total, which
leaves no room for a threshold with margin on both sides. Choosing 2x
sensitivity would buy it with a test that eventually flakes, and this phase has
already paid for that lesson once. 3x is what the measurement supports.
"""

from __future__ import annotations

import re
import sys
import time

import pytest

from src.rules import RulesSettings, evaluate

#: Items per batch. 2000 puts a batch at ~15-20 ms wall, two orders of magnitude
#: above any clock floor, while staying under a second per test.
_ITEMS = 2000

#: Batches per measurement. ``min`` discards a disturbed one.
_SAMPLES = 5

#: The published budget, unchanged. docs/34 §P9 Metrics.
_BUDGET_MS_PER_ITEM = 1.0

#: Ceiling for the drift ratio. Geometric midpoint of the worst normal
#: observation (0.258) and the cheapest 3x regression (0.613) is 0.398, rounded
#: to 0.40 — x1.55 of margin in both directions. **Not a tuning knob**: raising
#: it spends sensitivity, lowering it spends tolerance, and both were measured.
_MAX_DRIFT_RATIO = 0.40

_TITLES = (
    "Looking for a tool to track competitor pricing",
    "Weekly megathread - ask your questions here",
    "[HIRING] Senior Python developer, remote",
    "Our hiring process is broken and I need a tool to fix it",
    "Anyone know a good alternative to Zendesk?",
    "Use code SAVE20 at checkout",
    "AMA: I built a SaaS to $10k MRR",
    "struggling with invoicing and it is costing us",
)
_AUTHORS = (None, "a_real_person", "WikiTextBot", "[deleted]", "Botany_Nerd")
_NEGATIVE_TERMS = ("crypto", "nft", "forex")

#: A representative mix: admitted and rejected, every rule reached, so the
#: number is the cost of *judging*, not the cost of the cheapest early exit.
_ITEMS_FIXTURE = tuple(
    (_TITLES[i % len(_TITLES)], _AUTHORS[i % len(_AUTHORS)]) for i in range(_ITEMS)
)
_SETTINGS = RulesSettings()

#: The calibration reference: Python-level looping around C-level regex, the
#: same character as the rules — but built from patterns the rules do not use,
#: so a regression in our patterns moves the numerator only. A denominator that
#: tracks the numerator measures nothing.
_REF_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (r"\bzzq\w+\b", r"^\s*\[\s*qqz\s*\]", r"\bnever(?:more|theless)\b", r"\bxyzzy\b")
)
_REF_TEXT = " ".join(_TITLES) * 2


def _skip_under_a_tracer() -> None:
    """``coverage`` calls back into Python on every line.

    That inflates the rules far more than the reference — our code is Python,
    the reference is mostly C — so under instrumentation the ratio is not merely
    noisy, it is biased. Timing an instrumented interpreter measures the
    instrument.
    """
    if sys.gettrace() is not None:  # pragma: no cover - the tracer IS the reason
        pytest.skip("timing is meaningless under coverage or a debugger")


def _seconds_per_evaluation(repeats: int = 1) -> float:
    started = time.perf_counter()
    for title, author in _ITEMS_FIXTURE:
        for _ in range(repeats):
            evaluate(
                title=title,
                author=author,
                settings=_SETTINGS,
                negative_terms=_NEGATIVE_TERMS,
            )
    return (time.perf_counter() - started) / _ITEMS


def _seconds_per_reference() -> float:
    started = time.perf_counter()
    for _ in range(_ITEMS):
        lowered = _REF_TEXT.casefold()
        for pattern in _REF_PATTERNS:
            pattern.search(lowered)
    return (time.perf_counter() - started) / _ITEMS


def _drift_ratio(repeats: int = 1) -> float:
    """Rule cost over reference cost, sandwiched so drift lands in the denominator."""
    before = _seconds_per_reference()
    rules = _seconds_per_evaluation(repeats)
    after = _seconds_per_reference()
    reference = (before + after) / 2
    return rules / reference if reference else float("inf")


def test_rule_evaluation_stays_inside_the_budget():
    """A6, asserted at the published figure and not a millisecond looser.

    Wall clock is correct here despite DI18, and the reason is arithmetic rather
    than preference: at ~0.008 ms/item against a 1 ms budget there is ~100x of
    room, and the worst reading under twelve competing processes was 0.08 ms.
    Load cannot cross this. CPU time would in fact be *worse* — ``process_time``
    ticks at 15.625 ms on Windows, which over 2000 items quantises to
    0.0078 ms/item, so the measurement would be mostly clock artefact.
    """
    _skip_under_a_tracer()
    evaluate(title=_TITLES[0], settings=_SETTINGS)  # warm

    best = min(_seconds_per_evaluation() for _ in range(_SAMPLES)) * 1000
    assert best < _BUDGET_MS_PER_ITEM, (
        f"rule evaluation took {best:.4f} ms/item over {_ITEMS} items; "
        f"the budget is {_BUDGET_MS_PER_ITEM} ms. Normal is ~0.008 ms, so this is "
        f"a {best / 0.008:.0f}x regression, not a busy machine."
    )


def test_rule_evaluation_cost_has_not_drifted():
    """The sensitivity the budget above does not have.

    Ratio against a calibration workload timed either side of the measurement,
    so machine load divides out — the technique this phase proved on the feed
    parser after the absolute form failed seven times.

    Measured 2026-08-14, ``min`` of 5 batches: quiet 0.176-0.238, twelve busy
    processes 0.164-0.258, 2x-slower rules 0.326+, 3x-slower rules 0.613+. Load
    barely moves it, which is the whole point.
    """
    _skip_under_a_tracer()
    evaluate(title=_TITLES[0], settings=_SETTINGS)  # warm
    _seconds_per_reference()

    best = min(_drift_ratio() for _ in range(_SAMPLES))
    assert best < _MAX_DRIFT_RATIO, (
        f"rule evaluation costs {best:.3f}x the calibration workload; the ceiling "
        f"is {_MAX_DRIFT_RATIO}. Normal is 0.16-0.26 and a 3x regression measures "
        f"0.61+. This is a ratio, so a busy machine is not the explanation."
    )
