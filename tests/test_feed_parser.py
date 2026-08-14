"""The Atom parser, against golden fixtures.

Field-by-field against a committed ``.expected.json`` rather than "did it return
something": a count assertion passes while every field is wrong, and the point
of P5 is the fields.

The parity half of the proof -- that these dicts equal the HTML path's dicts --
lives in ``test_feed_parity.py``. These two files check different things and
neither replaces the other: this one pins absolute values, so a matching pair of
*wrong* answers still fails.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from lxml import etree

from src.discovery import FeedParseError, parse_feed

FIXTURES = Path(__file__).parent / "fixtures" / "atom"

#: Every fixture that has a recorded expectation. ``malformed.xml`` is absent by
#: design -- its expectation is an exception, asserted separately.
GOLDEN = ["listing_multireddit", "search", "empty"]


def _read(name: str) -> bytes:
    return (FIXTURES / f"{name}.xml").read_bytes()


def _expected(name: str) -> list[dict]:
    payload = json.loads((FIXTURES / f"{name}.expected.json").read_text(encoding="utf-8"))
    return payload["posts"]


def _comparable(posts: list[dict]) -> list[dict]:
    """Stringify datetimes so a dict comparison can be written in JSON."""
    return [
        {k: (str(v) if k == "created_utc" and v is not None else v) for k, v in post.items()}
        for post in posts
    ]


# ------------------------------------------------------------------ golden


@pytest.mark.parametrize("name", GOLDEN)
def test_fixture_matches_its_expected_json_field_by_field(name):
    """AC: 'fixtures assert field-by-field'.

    Whole-dict equality, so a key that appears or disappears fails too. A
    per-field loop over the *expected* keys would pass while the parser invented
    a new one, and P6 stores whatever this returns.
    """
    assert _comparable(parse_feed(_read(name))) == _expected(name)


def test_an_empty_feed_is_not_an_error():
    """A quiet subreddit sends a valid feed with no entries."""
    assert parse_feed(_read("empty")) == []


def test_a_malformed_feed_raises():
    """AC: 'a malformed feed raises ParseError, never a silent empty list'.

    The dangerous failure is not the crash. A truncated response read as ``[]``
    is indistinguishable from ``empty.xml`` above, so every poll would report
    "nothing new" and every poll would be believed.
    """
    with pytest.raises(FeedParseError):
        parse_feed(_read("malformed"))


def test_a_well_formed_non_feed_raises():
    """[28 §11 D3]: 'RSS silently deprecated by Reddit'.

    A deprecation notice or an interstitial can be perfectly well-formed XML.
    Well-formed is not the test; being a feed is.
    """
    with pytest.raises(FeedParseError):
        parse_feed(b"<?xml version='1.0'?><html><body>Gone</body></html>")


def test_an_empty_response_body_raises():
    """A 200 with zero bytes is a transport problem wearing a feed's clothes."""
    with pytest.raises(FeedParseError):
        parse_feed(b"")


# ------------------------------------------------------- the field rules


def test_the_submitted_by_footer_is_not_part_of_the_body():
    """Guards mutation M1.

    Reddit wraps ``<content>`` as ``<div class="md">…</div>`` plus a footer
    naming the author and linking the permalink. Reading the whole content text
    puts that footer in every body, where a keyword rule would match it on every
    single post.
    """
    posts = {p["id"]: p for p in parse_feed(_read("listing_multireddit"))}
    body = posts["t3_a000101"]["body"]
    assert body.startswith("We are three months in")
    assert "submitted by" not in body
    assert "[link]" not in body and "[comments]" not in body


def test_the_author_has_no_u_prefix():
    """Guards mutation M2. ``data-author`` is bare; ``<name>`` is ``/u/name``."""
    assert {p["author"] for p in parse_feed(_read("listing_multireddit"))} == {
        "redditor_0023",
        "redditor_0019",
        "redditor_0004",
    }


def test_permalinks_point_at_the_canonical_host():
    """The feed answers on old.reddit.com; stored URLs say www.reddit.com."""
    for post in parse_feed(_read("listing_multireddit")):
        assert post["url"].startswith("https://www.reddit.com/")


def test_a_multireddit_feed_keeps_each_entry_s_own_subreddit():
    """One request covers many subreddits (U1 makes that mandatory).

    A parser that read the feed-level ``<category>`` would label every post
    ``SaaS+startups``.
    """
    assert {p["subreddit"] for p in parse_feed(_read("listing_multireddit"))} == {
        "SaaS",
        "startups",
    }


def test_created_utc_prefers_published_over_updated():
    """``<updated>`` is an edit time and is 43 minutes later on this fixture.

    Reading it as the creation time would re-order the feed and, in P6, make an
    edited post look new on every poll.
    """
    posts = {p["id"]: p for p in parse_feed(_read("listing_multireddit"))}
    assert str(posts["t3_a000101"]["created_utc"]) == "2026-08-08 11:17:43"


def test_created_utc_falls_back_to_updated_when_published_is_absent():
    """Not every entry carries ``<published>``; the third one does not."""
    posts = {p["id"]: p for p in parse_feed(_read("listing_multireddit"))}
    assert str(posts["t3_a000103"]["created_utc"]) == "2026-08-08 10:42:19"


def test_created_utc_is_naive():
    """The schema stores naive UTC; an aware value breaks SQLite comparisons."""
    for post in parse_feed(_read("listing_multireddit")):
        assert post["created_utc"].tzinfo is None


def test_score_and_comment_count_are_unknown_not_zero():
    """A feed carries neither. ``0`` would be a fabricated fact."""
    for post in parse_feed(_read("listing_multireddit")):
        assert post["score"] is None
        assert post["num_comments"] is None


def test_a_link_post_has_an_empty_body():
    """No ``div.md`` on either path, so both produce ``""``."""
    posts = {p["id"]: p for p in parse_feed(_read("listing_multireddit"))}
    assert posts["t3_a000102"]["body"] == ""


def test_an_entry_with_no_content_element_is_not_an_error():
    """Search feeds omit ``<content>`` entirely on some results."""
    posts = {p["id"]: p for p in parse_feed(_read("search"))}
    assert posts["t3_a000202"]["body"] == ""


def test_html_entities_inside_the_body_are_resolved():
    """``&#39;`` must become an apostrophe, as it does on the HTML path."""
    posts = {p["id"]: p for p in parse_feed(_read("listing_multireddit"))}
    assert "Don't copy a competitor's price list." in posts["t3_a000103"]["body"]


def test_the_parser_accepts_str_as_well_as_bytes():
    """``FetchResult.text`` is a str; a captured file is bytes. Both arrive."""
    raw = _read("listing_multireddit")
    assert parse_feed(raw.decode("utf-8")) == parse_feed(raw)


# --------------------------------------------------------------- hardening


def test_declared_entities_are_not_expanded():
    """Untrusted network input into an XML parser.

    Entity *expansion* is the mechanism behind billion-laughs, and with a
    ``SYSTEM`` identifier it becomes local-file disclosure or -- with a remote
    DTD -- an outbound request made from inside the parser, routing around the
    network policy entirely. ``resolve_entities=False`` switches all of it off.

    An **internal** entity is used rather than ``file:///etc/passwd``: the
    file-based version passes on any machine where the path does not exist,
    which on Windows is every machine. That version was written first, survived
    the mutation that flips ``resolve_entities`` to ``True``, and is the reason
    this test now asserts expansion directly instead of asserting the absence of
    one particular file's contents.
    """
    hostile = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE feed [<!ENTITY inner "EXPANDEDVALUE">]>\n'
        b'<feed xmlns="http://www.w3.org/2005/Atom">'
        b"<entry><id>t3_evil</id><title>&inner;</title></entry></feed>"
    )
    try:
        posts = parse_feed(hostile)
    except FeedParseError:
        return  # refusing the document outright is also correct

    assert posts, "the document parsed but produced no entries"
    assert "EXPANDEDVALUE" not in (posts[0]["title"] or ""), (
        "the parser expanded a declared entity; resolve_entities must be False"
    )


# ----------------------------------------------------------------- volume


def test_a_hundred_entries_parse():
    """U5: ``?limit=100`` is honoured, so 100 is the real ceiling per request."""
    assert len(parse_feed(_read("listing_100"))) == 100


def test_parse_speed_stays_inside_the_budget():
    """Metric: 'Parse 100 entries fast', expressed as overhead over raw XML parsing.

    **The metric was redesigned on 2026-08-14, by operator decision, after the
    absolute form failed for the seventh time.** What changed is the instrument
    and the unit; what did not change is that the parser must be fast, and the
    test is now *stricter* than the figure it replaces (see below).

    *Why the absolute form could not be salvaged.* ``docs/DEFERRED-IMPROVEMENTS``
    DI18 recorded this as a good test that flaked under load. Measurement says
    otherwise, and the distinction matters:

    * **It never had the sensitivity it advertised.** The old docstring claimed
      *"a regression that doubled the cost would still fail"*. Against a
      deliberately 2x-slowed parser on a quiet machine, the original wall-clock
      form passed **5/5**. The parser costs ~25 ms and the budget was 50 ms, so
      2x landed just under the wire.
    * **Every one of its seven failures was the machine.** Two in P7, two in
      P8's gate, two in P9, all on unchanged parser code.
    * **``time.process_time`` was not enough.** Switching to CPU time helped and
      was tried first, but under contention a process burns more of its *own*
      CPU for identical work -- cache eviction and scheduling are real costs, and
      ``process_time`` counts them honestly. It still failed the gate at
      **115.6 ms CPU** against a 25 ms parser. On Windows it also has a
      **15.625 ms** tick behind a ``resolution`` field advertising 1e-07, so a
      single parse yields two distinct readings across 60 runs.

    *The measurement now.* Time raw ``lxml`` parsing of the same bytes, then
    ``parse_feed``, then raw parsing again; assert the ratio. Both halves are the
    same library on the same input, so whatever descheduled one descheduled the
    other and the machine divides out. The reference is deliberately **not**
    ``feed_parser``'s own ``_parser()``: it is constructed here, so a change
    there moves the numerator only.

    What the ratio means is *"how much work our extraction adds on top of
    parsing the XML at all"* -- which is the property this test was always trying
    to protect, and unlike milliseconds it is a property of the code rather than
    of the CPU it ran on.

    *Calibration*, 8-core machine, 2026-08-14, ``min`` of ``_SAMPLES``:

    ==========================  =======  =======  =======  =======
    Condition                   n        min      p90      max
    ==========================  =======  =======  =======  =======
    quiet                       20       0.872    1.321    1.345
    12 busy processes           15       0.862    0.963    0.980
    parse 2x slower             8        2.142    --       2.539
    parse 3x slower             6        2.982    --       3.970
    ==========================  =======  =======  =======  =======

    Load pushes the ratio **down**, not up: the reference suffers slightly more
    than ``parse_feed`` does. So contention cannot cause a false failure, which
    is the exact defect being fixed.

    ``_MAX_OVERHEAD_RATIO`` is the geometric midpoint of the worst normal
    observation (1.345) and the cheapest 2x regression (2.142) -- 1.697, rounded
    to 1.70. That leaves x1.26 of headroom in both directions, which is the most
    balanced split available and was chosen by arithmetic rather than by taste.

    .. note::

       **This is stricter than the retired 50 ms budget, not looser.** On the
       calibration machine the reference costs ~20.6 ms, so 1.70 corresponds to
       roughly **35 ms** for ``parse_feed`` -- where the old assertion allowed
       50 ms and, as established above, in practice allowed ~50 ms of a parser
       that had silently doubled. The performance requirement is not weakened by
       this change; it is tightened, and for the first time it is enforced.

    Skipped under a tracer. ``coverage`` calls back into Python on every line.
    That inflates the numerator far more than the denominator -- our extraction
    is Python, the reference is C -- so the ratio is not merely noisy under
    instrumentation, it is biased. Timing an instrumented interpreter measures
    the instrument.
    """
    if sys.gettrace() is not None:  # pragma: no cover - the tracer IS the reason
        pytest.skip("timing is meaningless under coverage or a debugger")

    raw = _read("listing_100")
    parse_feed(raw)  # warm up; the first parse pays costs no later parse pays
    _reference_seconds(raw)

    best = min(_overhead_ratio(raw) for _ in range(_SAMPLES))
    assert best < _MAX_OVERHEAD_RATIO, (
        f"parse_feed costs {best:.2f}x raw XML parsing of the same bytes; "
        f"the ceiling is {_MAX_OVERHEAD_RATIO}. Normal is 0.86-1.35 and a 2x "
        f"regression measures 2.14+. This is a ratio, so a busy machine is not "
        f"the explanation -- see this test's docstring."
    )


#: Raw parses per reference call. Sized so the reference costs about the same as
#: ``parse_feed`` itself, which keeps the ratio near 1 and keeps both sides well
#: clear of any clock floor.
_REF_XML_PARSES = 30

#: Calls averaged inside one timing, and timings taken per assertion. ``min``
#: over samples discards a disturbed one; five is enough because the ratio's
#: spread is small (see the calibration table) and each sample costs ~330 ms.
_INNER = 5
_SAMPLES = 5

#: The geometric midpoint of the worst normal ratio and the cheapest detected
#: 2x regression. **Not a tuning knob** -- raising it spends regression
#: sensitivity, lowering it spends tolerance, and both were measured.
_MAX_OVERHEAD_RATIO = 1.70


def _time(fn, n: int = _INNER) -> float:
    """Mean wall seconds per call over ``n`` calls.

    Wall clock is correct *here* precisely because the result is only ever used
    as the numerator or denominator of a ratio measured moments later. It was
    the absolute use of wall clock that was wrong, not the clock.
    """
    started = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - started) / n


def _reference_seconds(raw: bytes) -> float:
    """Seconds to parse ``raw`` as XML ``_REF_XML_PARSES`` times, and nothing else.

    Constructed independently of ``feed_parser._parser()`` on purpose: sharing it
    would let a change to the production parser's settings move the reference,
    and a denominator that tracks the numerator measures nothing.
    """

    def once() -> None:
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        for _ in range(_REF_XML_PARSES):
            etree.fromstring(raw, parser=parser)

    return _time(once)


def _overhead_ratio(raw: bytes) -> float:
    """``parse_feed`` cost divided by raw-XML cost, sandwiched to catch drift.

    The reference is measured *before and after* the parse and averaged, so a
    machine that got busier partway through the sample shows up in the
    denominator rather than being attributed to the parser.
    """
    before = _reference_seconds(raw)
    parsed = _time(lambda: parse_feed(raw))
    after = _reference_seconds(raw)
    reference = (before + after) / 2
    return parsed / reference if reference else float("inf")
