"""Acceptance A5 — *"property test: no input crashes"*, read strictly.

Two departures from the criterion as written, both deliberate:

* **"No input crashes" is read to include "no input hangs."** Five compiled
  patterns run against attacker-supplied post bodies, and a catastrophic
  backtrack does not raise — it stalls the worker. A test that only catches
  exceptions would report green while the pipeline was wedged.
* **No `hypothesis`.** It is not installed and not in `requirements.txt`, and
  ARCHITECTURE_FREEZE §5 closes the technology set — adding a dependency needs a
  §11 amendment backed by a failed measurement, which "it would be convenient"
  is not. Generation here is stdlib `random` under a **fixed seed**, so a
  failure reproduces exactly rather than "sometimes on Tuesdays".
"""

from __future__ import annotations

import random
import string
import time
import unicodedata

import pytest

from src.rules import ADMITTED, REASONS, RulesSettings, evaluate
from src.rules.authors import check_author
from src.rules.competitors import competitor_mentions, registry_from_mapping
from src.rules.keywords import check_negative_terms, match_tiers, normalise
from src.rules.structural import check_length, check_structural

SEED = 20260814
TIERS = {"high_intent": ["looking for", "any recommendations"], "medium_intent": ["how do i"]}
NEG = ("crypto", "nft", "forex")
REGISTRY = registry_from_mapping({"Notion": ["notion.so"], "Airtable": ["air table"]})


# --------------------------------------------------------- the nasty corpus

#: Inputs chosen because each has broken a text pipeline somewhere before.
HOSTILE: tuple[str, ...] = (
    "",
    " ",
    "\n",
    "\t\r\n ",
    "\x00",  # NUL
    "\ud800",  # lone high surrogate — legal in a str, illegal in UTF-8
    "\udfff",  # lone low surrogate
    "﻿",  # BOM as content
    "​‌‍",  # zero-width space / non-joiner / joiner
    "‮" + "gnirts desrever" + "‬",  # RTL override
    "العربية",  # Arabic
    "\U0001f600\U0001f4a9\U0001f1ec\U0001f1e7",  # emoji incl. a flag pair
    "é" * 500,  # combining acutes, unnormalised
    unicodedata.normalize("NFKD", "ﬁ" * 200),  # ligature decomposition
    "A" * 100_000,  # 100 kB single token
    ("word " * 20_000),  # 100 kB of tokens
    "\\" * 1000,  # backslashes
    "[" * 1000,  # unbalanced brackets — regex-shaped
    "(" * 500 + ")" * 500,
    ".*" * 500,  # looks like a pattern, is data
    "hiring" * 5000,
    "[HIRING]" * 2000,
    "a" * 50_000 + "!",  # the classic backtracking bait tail
    "\n".join(["megathread"] * 5000),
)


def _random_text(rng: random.Random, size: int) -> str:
    alphabet = string.printable + "áéíóú漢字한글​‮﻿\U0001f600"
    return "".join(rng.choice(alphabet) for _ in range(size))


def _generated(count: int = 300) -> list[str]:
    rng = random.Random(SEED)
    return [_random_text(rng, rng.randint(0, 400)) for _ in range(count)]


ALL_INPUTS = list(HOSTILE) + _generated()


# ------------------------------------------------------------ no input crashes


@pytest.mark.parametrize("text", HOSTILE, ids=lambda t: f"len{len(t)}")
def test_no_hostile_input_raises_from_any_rule(text: str):
    """Every entry point, over every hostile string."""
    assert check_structural(text).reason in (None, *REASONS)
    assert check_length(text, 80).reason in (None, *REASONS)
    assert check_negative_terms(text, NEG).reason in (None, *REASONS)
    assert check_author(text).reason in (None, *REASONS)
    assert isinstance(match_tiers(text, TIERS), dict)
    assert isinstance(competitor_mentions(text, REGISTRY), list)
    assert isinstance(normalise(text), str)


def test_no_generated_input_raises():
    """300 seeded random strings through the composed engine."""
    for text in _generated():
        result = evaluate(title=text, author=text[:40] or None, text=text, negative_terms=NEG)
        assert result.reason in (None, *REASONS)


@pytest.mark.parametrize("value", [None, ""])
def test_none_and_empty_are_handled_everywhere(value):
    assert check_structural(value) == ADMITTED
    assert check_author(value) == ADMITTED
    assert check_negative_terms(value or "", NEG) == ADMITTED
    assert competitor_mentions(value, REGISTRY) == []
    assert check_length(value, 80).rejected  # empty *is* too short — a result, not a crash


def test_a_100kb_body_is_judged_without_incident():
    body = "we are looking for a tool. " * 4000
    result = evaluate(title="a normal title", text=body, negative_terms=NEG)
    assert result.reason in (None, *REASONS)


# ----------------------------------------------------- and no input hangs

#: Generous enough that a slow machine does not fail it, tight enough that a
#: catastrophic backtrack — which is seconds-to-forever, not milliseconds —
#: cannot pass. The gap between "slow" and "wedged" is orders of magnitude.
_REDOS_BUDGET_S = 2.0


@pytest.mark.parametrize(
    "payload",
    [
        "a" * 50_000 + "!",
        "[" * 5000,
        "hiring " * 20_000,
        "(" * 2000 + ")" * 2000,
        " " * 100_000,
        "‮" * 50_000,
    ],
    ids=["long-a", "brackets", "repeated-word", "nested-parens", "spaces", "rtl-flood"],
)
def test_pathological_input_does_not_wedge_the_rules(payload: str):
    """⚠️ The half of A5 the criterion does not say out loud.

    ``re`` has no timeout. A pattern that backtracks catastrophically returns
    control to nobody, so the failure is a hung worker rather than a traceback —
    invisible to a test that only catches exceptions.

    CPU time, not wall clock: on a loaded machine wall time measures the
    neighbours, which is the DI18 trap this project has already paid for once.
    """
    started = time.process_time()
    evaluate(title=payload, author=payload[:50], text=payload, negative_terms=NEG)
    competitor_mentions(payload, REGISTRY)
    match_tiers(payload, TIERS)
    elapsed = time.process_time() - started
    assert elapsed < _REDOS_BUDGET_S, (
        f"rules burned {elapsed:.2f}s of CPU on a {len(payload)}-char input; "
        f"budget is {_REDOS_BUDGET_S}s. A catastrophic backtrack does not raise, "
        f"it wedges the worker."
    )


# ------------------------------------------------------------- invariants


def test_a_rejection_always_carries_a_known_reason():
    """The closed vocabulary holds across every input, not just the tidy ones."""
    for text in ALL_INPUTS:
        result = evaluate(title=text, author=text[:40] or None, negative_terms=NEG)
        if result.rejected:
            assert result.reason in REASONS
        else:
            assert result.reason is None and result.detail is None


def test_normalise_is_idempotent():
    """normalise(normalise(x)) == normalise(x), or the pipeline is order-dependent."""
    for text in ALL_INPUTS[:100]:
        once = normalise(text)
        assert normalise(once) == once


def test_normalise_splits_decomposed_accents_and_that_is_a_known_gap():
    """⚠️ Documents real behaviour, and it is not the behaviour you would want.

    This test was first written as *"normalise never lengthens the token count"*
    — an invariant that felt obviously true and is false. `normalise` replaces
    every non-`\\w`, non-`\\s` character with a space, and a **combining mark**
    (Unicode category Mn) is neither: `str.isalnum()` is False for a bare
    U+0301, so `\\w` does not match it.

    The consequence is that decomposed text is torn apart::

        normalise("e\\u0301e\\u0301e\\u0301")  ->  "e e e"

    and, worse, decomposed and precomposed spellings of the same word do not
    compare equal::

        normalise("cafe\\u0301") != normalise("caf\\u00e9")

    So an operator whose negative vocabulary is typed one way silently fails to
    match text typed the other. Registered as **DI26**; the fix is one
    `unicodedata.normalize("NFKC", …)` call, and it is not made here because
    `keywords.py` is Stage 2's and this is Stage 5.

    Asserted rather than left implicit: a gap nobody has written down is a gap
    that gets rediscovered.
    """
    decomposed = "é" * 3
    assert normalise(decomposed) == "e e e"
    assert normalise("café") != normalise("café")


def test_normalise_output_is_always_clean():
    """The invariants that are actually true, over the whole corpus.

    An earlier draft asserted *"normalise never lengthens the token count"*
    twice, and it is false twice over: punctuation-to-space is a **splitting**
    operation by design (`[HIRING][HIRING]` becomes two tokens, correctly), and
    combining marks split too (the separate DI26 case above). Both drafts were
    written from intuition; both were wrong. These four are properties the
    function genuinely has.
    """
    for text in ALL_INPUTS[:150]:
        out = normalise(text)
        assert out == out.strip(), "no leading or trailing whitespace"
        assert "  " not in out, "runs of whitespace are collapsed to one space"
        assert out == out.casefold(), "output is casefolded"
        assert "\t" not in out and "\n" not in out, "all whitespace is a plain space"


def test_disabling_the_rules_admits_every_input():
    """The rollback holds over the hostile corpus too, not just tidy titles."""
    off = RulesSettings(enabled=False)
    for text in HOSTILE:
        assert evaluate(title=text, author=text[:40] or None, settings=off) == ADMITTED


def test_evaluation_is_deterministic():
    """Same input, same verdict — twice. A rule with hidden state is not a rule."""
    for text in ALL_INPUTS[:150]:
        first = evaluate(title=text, author=text[:40] or None, negative_terms=NEG)
        second = evaluate(title=text, author=text[:40] or None, negative_terms=NEG)
        assert first == second
