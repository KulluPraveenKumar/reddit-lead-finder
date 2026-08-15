"""DI13 at the model layer: an unknown score reaches the database as NULL.

`src/scoring/legacy.py` has stated the intent since before Phase 1 — *"the Lead
row still stores NULL, because 'unknown' and 'zero upvotes' are different facts
and conflating them would make the number a quiet lie"* — and the schema has
always said `nullable=True` with no server default.

**It never held.** `models.py` carried a Python-side `default=0` on both columns,
which SQLAlchemy applies whenever the value is None at INSERT. Measured on the
live database 2026-08-15: **0 of 492 rows carry NULL** in either column, on a
corpus containing leads from the search path that cannot know a score.

P11 is where it stops being cosmetic — docs/34 §P11 task 4 is *"score back-fill
for search-sourced leads"*, and there is nothing to back-fill while the default
has already answered the question wrongly.
"""

from __future__ import annotations

import csv
import datetime
import io

import pytest

from src.db.models import Lead

NOW = datetime.datetime(2026, 8, 15, 12, 0, 0)


@pytest.fixture
def session(temp_db):
    from src.db.database import get_session

    with get_session() as s:
        yield s


def add(session, **kwargs) -> Lead:
    defaults = {
        "reddit_id": "t3_aaa",
        "subreddit": "SaaS",
        "author": "someone",
        "title": "Looking for a CRM",
        "url": "https://www.reddit.com/r/SaaS/comments/aaa/x/",
        "created_utc": NOW,
    }
    lead = Lead(**{**defaults, **kwargs})
    session.add(lead)
    session.commit()
    return lead


def test_an_unknown_score_persists_as_null(session):
    """The property the schema always allowed and the model always prevented."""
    lead = add(session, score=None, num_comments=None)
    session.expire_all()
    stored = session.get(Lead, lead.id)
    assert stored.score is None
    assert stored.num_comments is None


def test_a_known_zero_persists_as_zero(session):
    """The other half, and the reason this is not simply "make it nullable":
    a measured zero must stay a measured zero."""
    lead = add(session, score=0, num_comments=0)
    session.expire_all()
    stored = session.get(Lead, lead.id)
    assert stored.score == 0
    assert stored.num_comments == 0


def test_an_unset_score_is_also_null(session):
    """A caller that never mentions the column is saying "unknown", not "zero"."""
    lead = add(session)
    session.expire_all()
    assert session.get(Lead, lead.id).score is None


def test_the_legacy_scorer_still_treats_unknown_as_zero_for_arithmetic(session):
    """R20. `intent_score` must not move: `LeadScorer.score_post` coerces with
    `upvotes or 0`, and its comment says why — the coercion is for arithmetic
    only, and the row still stores NULL."""
    from src.scoring import LeadScorer

    scorer = LeadScorer({"keywords": {"high_intent": ["looking for"]}})
    with_none = scorer.score_post("Looking for a CRM", upvotes=None, num_comments=None)
    with_zero = scorer.score_post("Looking for a CRM", upvotes=0, num_comments=0)
    assert with_none["total"] == with_zero["total"]


def test_a_null_score_exports_as_an_empty_csv_cell_not_the_word_none(session):
    """The 13-column CSV is part of the R20 legacy contract. `csv.writer` renders
    None as an empty field, which is the honest cell for "not known" — this pins
    it rather than assuming it."""
    output = io.StringIO()
    csv.writer(output).writerow([1, None, 2])
    assert output.getvalue() == "1,,2\r\n"


def test_a_null_score_renders_as_an_em_dash_and_not_as_the_string_none(client, session):
    """Jinja renders None as the literal "None". Every row that HAS a value is
    byte-identical, which is all 459 legacy leads — so R20 is untouched."""
    add(session, score=None, num_comments=None, intent_score=10.0, matched_keywords="")
    body = client.get("/").get_data(as_text=True)
    assert ">None<" not in body
    assert "—" in body


def test_sorting_by_a_nullable_column_does_not_raise(client, session):
    """SQL orders NULLs without complaint; a Python `sorted()` over them would
    not. This is the read path an operator actually clicks."""
    add(session, reddit_id="t3_a", score=None, num_comments=None)
    add(session, reddit_id="t3_b", score=10, num_comments=5)
    assert client.get("/?sort_by=num_comments").status_code == 200
    assert client.get("/?sort_by=score").status_code == 200


def test_the_extractor_reports_unknown_rather_than_zero_when_the_element_is_absent():
    """DI13 as the register states it, at the parser.

    Three cases, and the middle one is why this is not a one-line change to None:
    old reddit renders exactly "comment" for a post with none, which is a
    MEASUREMENT of zero rather than an absence.
    """
    from bs4 import BeautifulSoup

    from src.reddit_client import RedditClient

    client = RedditClient(config={})

    def extract(comments_html: str):
        html = (
            '<div class="thing" data-fullname="t3_x" data-author="a" '
            'data-subreddit="SaaS" data-score="5" data-timestamp="1700000000000">'
            '<a class="title" href="/r/SaaS/comments/x/">T</a>' + comments_html + "</div>"
        )
        thing = BeautifulSoup(html, "lxml").select_one("div.thing")
        return client._extract_post(thing)

    assert extract('<a class="comments">12 comments</a>')["num_comments"] == 12
    assert extract('<a class="comments">comment</a>')["num_comments"] == 0
    assert extract("")["num_comments"] is None
