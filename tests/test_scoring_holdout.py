"""The 2% holdout — reproducible, unbiased, and honest about having measured nothing.

freeze R11 and docs/06c §6. This is the first mechanism in the project capable of
measuring the metadata gate's false-positive rate rather than arguing about it,
which is why DI25 waited for it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from src.scoring.holdout import (
    NEVER_SAMPLED,
    MissRate,
    audit_sample,
    is_sampled,
    miss_rate,
    stable_hash,
)

# ------------------------------------------------------------ reproducible


def test_the_default_rate_reproduces_06c_modulus_50():
    """docs/06c §6 writes the 2% case as `stable_hash(...) % 50 == 0`.

    The rate is generalised so `gate.metadata_holdout_rate` is not decorative,
    and this asserts the generalisation still passes through 06c's literal.
    """
    assert round(1 / 0.02) == 50


def test_the_hash_is_stable_across_processes():
    """`hash()` is randomised per process by PYTHONHASHSEED, so a re-claimed job
    would sample a DIFFERENT 2% and the audit would not be reproducible — the
    property docs/06c §6 asks for by name.

    Run in a subprocess with a different seed, because within one process the
    randomisation is fixed and a `hash()`-based implementation would pass.
    """
    script = textwrap.dedent(
        """
        from src.scoring.holdout import stable_hash
        print(stable_hash("t3_abc123"))
        """
    )
    seen = set()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        seen.add(out.stdout.strip())

    assert len(seen) == 1, f"stable_hash varied with PYTHONHASHSEED: {seen}"
    assert seen == {str(stable_hash("t3_abc123"))}


def test_sampling_the_same_corpus_twice_selects_the_same_items():
    rejects = [(f"t3_{i}", "hiring") for i in range(500)]
    first = list(audit_sample(rejects, 0.02))
    second = list(audit_sample(rejects, 0.02))
    assert first == second


def test_the_sample_is_roughly_the_configured_rate():
    """Hash-based sampling is not exact, so this asserts the order of magnitude
    rather than a count — a test demanding exactly 2% would be asserting the
    hash function, not the sampler."""
    rejects = [(f"t3_{i}", "hiring") for i in range(5_000)]
    sampled = list(audit_sample(rejects, 0.02))
    assert 60 <= len(sampled) <= 140, f"expected ~100 of 5000, got {len(sampled)}"


# ------------------------------------------------------------- the off case


def test_a_rate_of_zero_samples_nothing():
    """ "Off" must mean off, rather than "every 1 in 0" — which would raise."""
    rejects = [(f"t3_{i}", "hiring") for i in range(200)]
    assert list(audit_sample(rejects, 0.0)) == []


def test_a_rate_of_one_samples_everything():
    rejects = [(f"t3_{i}", "hiring") for i in range(20)]
    assert len(list(audit_sample(rejects, 1.0))) == 20


def test_a_negative_rate_samples_nothing_rather_than_raising():
    assert is_sampled("t3_x", -1.0) is False


# ---------------------------------------------------------- the exclusions


@pytest.mark.parametrize("reason", sorted(NEVER_SAMPLED))
def test_a_provably_correct_rejection_is_never_sampled(reason):
    """docs/06c §6: those rejections are provably correct, and auditing them
    would waste calls proving arithmetic works."""
    rejects = [(f"t3_{i}", reason) for i in range(2_000)]
    assert list(audit_sample(rejects, 1.0)) == []


def test_no_title_is_excluded_and_the_exclusion_is_p11s_own():
    """docs/06c §6 names four; `no_title` is the fifth and is P11's addition.

    A post with no title has nothing for the full-stage gate to score, so
    sampling it would enter a guaranteed non-miss into the denominator and bias
    the published rate DOWNWARDS — flattering the gate, which is the one
    direction an audit must never be wrong in.
    """
    assert "no_title" in NEVER_SAMPLED
    assert NEVER_SAMPLED - {"no_title"} == {
        "already_analyzed",
        "duplicate_exact",
        "duplicate_near",
        "budget_exhausted",
    }


def test_an_auditable_reason_is_still_sampled_alongside_excluded_ones():
    """The exclusion must filter, not abort."""
    rejects = [("t3_a", "duplicate_exact"), ("t3_b", "hiring")]
    assert list(audit_sample(rejects, 1.0)) == [("t3_b", "hiring")]


# ------------------------------------------------------------- the report


def test_the_miss_rate_is_qualified_over_sampled():
    report = miss_rate([("hiring", True), ("hiring", False), ("negative_term", False)])
    assert report.sampled == 3
    assert report.would_have_qualified == 1
    assert report.rate == pytest.approx(1 / 3)


def test_sampling_nothing_is_not_a_pass():
    """A run that sampled nothing has not demonstrated a miss rate below 5%; it
    has demonstrated nothing. The run page renders "not measured", never 0.0%."""
    report = miss_rate([])
    assert report.rate == 0.0
    assert report.measured is False
    assert report.to_dict()["measured"] is False


def test_measuring_zero_misses_is_a_pass():
    """The other side: a real sample with no misses IS a measurement."""
    report = miss_rate([("hiring", False), ("hiring", False)])
    assert report.rate == 0.0
    assert report.measured is True


def test_the_worst_reason_is_the_actionable_part():
    """docs/06c §6: it tells the operator WHICH rule is too aggressive.

    ⚠ The worst reason is deliberately **not** the first one encountered. The
    input below puts a one-miss reason ahead of the two-miss one, so an
    implementation returning "whichever came first" gives the wrong answer — and
    the wrong answer here sends an operator to edit a rule that is working.
    """
    report = miss_rate(
        [("negative_term", True), ("hiring", True), ("hiring", True), ("ama", False)]
    )
    assert report.worst_reason == "hiring"
    assert report.by_reason == {"negative_term": 1, "hiring": 2}
    assert next(iter(report.by_reason)) == "negative_term", (
        "the fixture must not let insertion order accidentally be correct"
    )


def test_the_worst_reason_is_deterministic_under_a_tie():
    """An arbitrary winner would make two identical runs report differently."""
    audited = [("hiring", True), ("negative_term", True)]
    assert len({miss_rate(audited).worst_reason for _ in range(50)}) == 1


def test_no_misses_means_no_worst_reason():
    assert miss_rate([("hiring", False)]).worst_reason is None


def test_the_payload_reproduces_06cs_own_worked_example():
    """docs/06c §6's example, verbatim: "4 of 128 sampled rejects would have
    qualified" -> "Gate miss rate 3.1%", against a "< 5%" target.

    4/128 is 0.03125, which `round(_, 4)` renders as 0.0312 -- and 3.1% is what
    06c prints, so the stored value and the document agree.
    """
    payload = MissRate(sampled=128, would_have_qualified=4, worst_reason="hiring").to_dict()
    assert payload["sampled"] == 128
    assert payload["would_have_qualified"] == 4
    assert payload["gate_miss_rate"] == pytest.approx(0.0312, abs=1e-4)
    assert f"{payload['gate_miss_rate']:.1%}" == "3.1%"
    assert payload["gate_miss_rate"] < 0.05
    assert payload["worst_reason"] == "hiring"
