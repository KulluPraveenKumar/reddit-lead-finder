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
    """Metric: 'Parse 100 entries < 50 ms'.

    Measured over several runs and compared on the best one: a single timing on
    a shared CI runner measures the runner's neighbours as much as the parser.
    The budget is the published one; the headroom here is real, not a fudge --
    a regression that doubled the cost would still fail.

    Skipped under a tracer. ``coverage`` calls back into Python on every line,
    which multiplies the measured cost several times over -- so without this the
    coverage run, which the gate requires, would fail on a parser that is well
    inside budget. Timing an instrumented interpreter measures the instrument.
    """
    if sys.gettrace() is not None:  # pragma: no cover - the tracer IS the reason
        pytest.skip("timing is meaningless under coverage or a debugger")

    raw = _read("listing_100")
    best = min(_time_one(raw) for _ in range(5))
    assert best < 0.050, f"100 entries took {best * 1000:.1f} ms, budget is 50 ms"


def _time_one(raw: bytes) -> float:
    started = time.perf_counter()
    parse_feed(raw)
    return time.perf_counter() - started
