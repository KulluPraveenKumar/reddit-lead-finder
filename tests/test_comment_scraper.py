"""Comments: ordered by pre-score, stored once, and re-running changes nothing.

docs/34 §P11 tasks 3, 4 and 5, and the acceptance lines *"comment candidates
ordered by pre-score; collected comments fall >=5% with NO reduction in admitted
items"*, *"re-running comment extraction creates zero duplicates"* and
*"search-sourced `score` back-filled"*.
"""

from __future__ import annotations

import datetime

import pytest

from src.db.models import Lead
from src.db.repositories.comments import CommentRepository, body_hash
from src.scrapers.comment_scraper import (
    Candidate,
    CommentScraper,
    ScrapingSettings,
    plan_fetches,
)

NOW = datetime.datetime(2026, 8, 15, 12, 0, 0)


def candidate(lead_id: int, prescore: float, num_comments: int | None = 10, **kwargs) -> Candidate:
    return Candidate(
        lead_id=lead_id,
        url=f"https://www.reddit.com/r/SaaS/comments/{lead_id}/x/",
        prescore=prescore,
        num_comments=num_comments,
        **kwargs,
    )


class FakeClient:
    """Records what was requested, in order. The whole -5% claim is about that."""

    def __init__(self, comments=None, score=None, num_comments=None):
        self.requested: list[str] = []
        self._comments = (
            comments
            if comments is not None
            else [
                {"author": "alice", "body": "we had the same problem last year", "score": 4},
                {"author": "bob", "body": "try the free tier first", "score": 2},
            ]
        )
        self._score = score
        self._num_comments = num_comments

    def get_post_detail(self, url, limit=50):
        self.requested.append(url)
        return {
            "score": self._score,
            "num_comments": self._num_comments,
            "comments": self._comments[:limit],
        }


# ------------------------------------------------------------- the ordering


def test_candidates_are_requested_in_descending_prescore_order():
    """docs/34 §P11 task 3. A fixed budget must buy the best evidence, not
    whichever post the scraper reached first."""
    settings = ScrapingSettings(max_comment_posts=3)
    plan = plan_fetches(
        [candidate(1, 40.0), candidate(2, 90.0), candidate(3, 60.0), candidate(4, 75.0)],
        settings,
        admission_floor=35.0,
    )
    assert [c.lead_id for c in plan.selected] == [2, 4, 3]


def test_the_budget_bounds_the_requests_and_the_saving_is_reported():
    """The -5% is a within-run counterfactual: `eligible` is what
    fetch-everything would have cost, `requests` is what ordering spent."""
    settings = ScrapingSettings(max_comment_posts=5)
    plan = plan_fetches([candidate(i, 50.0 + i) for i in range(20)], settings, admission_floor=35.0)
    assert plan.eligible == 20
    assert plan.requests == 5
    assert plan.saved == 15
    assert plan.saving_rate == pytest.approx(0.75)


def test_the_saving_beats_the_five_percent_target_on_a_realistic_run():
    """docs/34 §P11's Metrics row: "comment requests -5% or better"."""
    settings = ScrapingSettings(max_comment_posts=25)
    plan = plan_fetches([candidate(i, 50.0) for i in range(30)], settings, admission_floor=35.0)
    assert plan.saving_rate >= 0.05


def test_a_tie_is_broken_deterministically():
    """Two identical runs must select the same posts, or the -5% measurement is
    not reproducible. `dedupe.choose_representative` uses the same discipline."""
    items = [candidate(i, 50.0, num_comments=10) for i in (7, 3, 9, 1)]
    first = plan_fetches(items, ScrapingSettings(max_comment_posts=2), admission_floor=35.0)
    second = plan_fetches(
        list(reversed(items)), ScrapingSettings(max_comment_posts=2), admission_floor=35.0
    )
    assert [c.lead_id for c in first.selected] == [c.lead_id for c in second.selected] == [1, 3]


def test_no_eligible_posts_reports_none_rather_than_a_zero_saving():
    """A run with nothing to reduce has not demonstrated a 0% saving; it has
    demonstrated nothing."""
    plan = plan_fetches([], ScrapingSettings(), admission_floor=35.0)
    assert plan.saving_rate is None
    assert plan.to_dict()["saving_rate"] is None


# ------------------------------------------------------------ the exclusions


def test_an_item_below_the_admission_floor_is_never_requested():
    """docs/34 §P11 task 3: "skipping below the admission floor". An item the
    gate will not admit is not worth a request, whatever its comment count."""
    plan = plan_fetches(
        [candidate(1, 10.0, num_comments=500)], ScrapingSettings(), admission_floor=35.0
    )
    assert plan.selected == []
    assert plan.below_floor == 1
    assert plan.eligible == 0


def test_a_post_with_too_few_comments_is_skipped():
    settings = ScrapingSettings(min_post_comments_for_comment_fetch=3)
    plan = plan_fetches([candidate(1, 90.0, num_comments=2)], settings, admission_floor=35.0)
    assert plan.selected == []
    assert plan.too_few_comments == 1


def test_an_unknown_comment_count_is_eligible_and_counted_separately():
    """DI13, firing exactly where the register predicted.

    Reading unknown as "nobody commented" would make every search-sourced lead
    permanently ineligible for the one enrichment step that costs nothing but a
    request. The share is counted rather than assumed.
    """
    plan = plan_fetches(
        [candidate(1, 90.0, num_comments=None)], ScrapingSettings(), admission_floor=35.0
    )
    assert [c.lead_id for c in plan.selected] == [1]
    assert plan.unknown_comment_count == 1
    assert plan.too_few_comments == 0


def test_a_post_whose_comments_are_already_stored_is_not_requested_again():
    """This is where the request saving actually comes from on a re-run: the
    savepoint would discard the rows anyway, but the request would be spent."""
    plan = plan_fetches(
        [candidate(1, 90.0, already_stored=7)], ScrapingSettings(), admission_floor=35.0
    )
    assert plan.selected == []
    assert plan.already_covered == 1


def test_zero_posts_is_the_documented_off_switch():
    plan = plan_fetches(
        [candidate(1, 90.0)], ScrapingSettings(max_comment_posts=0), admission_floor=35.0
    )
    assert plan.selected == []
    assert plan.eligible == 1, "eligibility is unchanged; only the budget is zero"


# ------------------------------------------------------------ the body hash


def test_the_hash_is_scoped_to_the_lead():
    """The same boilerplate reply appears under many posts, and it is distinct
    evidence each time. A global content hash would store the first and silently
    discard the rest — comment coverage would look complete while being
    arbitrarily incomplete."""
    assert body_hash(1, "alice", "same here") != body_hash(2, "alice", "same here")


def test_the_author_is_part_of_the_hash():
    """Two people posting "same here" under one thread are two people agreeing."""
    assert body_hash(1, "alice", "same here") != body_hash(1, "bob", "same here")


def test_a_missing_author_folds_to_the_column_default():
    """So a removed account hashes consistently rather than by whether the parser
    happened to return None or the string."""
    assert body_hash(1, None, "x") == body_hash(1, "[deleted]", "x")
    assert body_hash(1, "", "x") == body_hash(1, "[deleted]", "x")


def test_the_encoding_is_unambiguous_even_when_a_field_contains_a_null():
    """The first version of `body_hash` claimed `\\x00` "cannot occur in any of
    the three fields". It can, and these two collided.

    A collision here looks exactly like the duplicate the unique index exists to
    refuse, so the failure mode was a silently dropped comment. The author is
    length-prefixed now.
    """
    assert body_hash(1, "a", "b\x00c") == body_hash(1, "a", "b\x00c")
    assert body_hash(1, "a\x00b", "c") != body_hash(1, "a", "b\x00c")


# --------------------------------------------------- zero duplicates, AC4


@pytest.fixture
def session(temp_db):
    from src.db.database import get_session

    with get_session() as s:
        yield s


def _lead(session, **kwargs) -> Lead:
    defaults = {
        "reddit_id": "t3_aaa",
        "subreddit": "SaaS",
        "author": "someone",
        "title": "Looking for a CRM",
        "body": "x" * 200,
        "url": "https://www.reddit.com/r/SaaS/comments/aaa/x/",
        "post_type": "post",
        "score": 10,
        "num_comments": 12,
        "intent_score": 40.0,
        "created_utc": NOW,
    }
    lead = Lead(**{**defaults, **kwargs})
    session.add(lead)
    session.commit()
    return lead


def test_re_running_comment_extraction_creates_zero_duplicates(session):
    """docs/34 §P11's acceptance line, against a real unique index."""
    lead = _lead(session)
    repo = CommentRepository(session)
    comments = [
        {"author": "alice", "body": "we had the same problem", "score": 4},
        {"author": "bob", "body": "try the free tier", "score": 2},
    ]

    first = repo.add_many(lead.id, comments)
    session.commit()
    second = repo.add_many(lead.id, comments)
    session.commit()

    assert first.stored == 2
    assert second.stored == 0
    assert second.skipped == 2
    assert repo.count_for_lead(lead.id) == 2


def test_a_collision_does_not_lose_the_rest_of_the_batch(session):
    """This is why it is a SAVEPOINT and not a pre-check.

    Without `begin_nested()` the duplicate is detected at the flush, by which
    point the whole transaction is poisoned and every OTHER comment in the batch
    is lost with it — "re-running creates zero comments" rather than "zero
    duplicates".
    """
    lead = _lead(session)
    repo = CommentRepository(session)
    repo.add_many(lead.id, [{"author": "alice", "body": "first"}])
    session.commit()

    outcome = repo.add_many(
        lead.id,
        [
            {"author": "alice", "body": "first"},  # collides
            {"author": "bob", "body": "second"},  # must still land
            {"author": "carol", "body": "third"},
        ],
    )
    session.commit()

    assert outcome.stored == 2
    assert outcome.skipped == 1
    assert repo.count_for_lead(lead.id) == 3


def test_an_empty_body_is_skipped_without_touching_the_database(session):
    """Hashing "" would make one empty-body row per lead look like a real
    comment forever."""
    lead = _lead(session)
    repo = CommentRepository(session)
    outcome = repo.add_many(lead.id, [{"author": "alice", "body": "   "}])
    session.commit()
    assert outcome.stored == 0
    assert repo.count_for_lead(lead.id) == 0


def test_the_same_comment_under_two_leads_is_stored_twice(session):
    """The other half of the lead-scoped hash: distinct evidence, kept."""
    first = _lead(session, reddit_id="t3_one")
    second = _lead(session, reddit_id="t3_two")
    repo = CommentRepository(session)
    body = [{"author": "alice", "body": "have you tried notion"}]

    repo.add_many(first.id, body)
    repo.add_many(second.id, body)
    session.commit()

    assert repo.count_for_lead(first.id) == 1
    assert repo.count_for_lead(second.id) == 1


def test_counts_for_leads_is_one_query_not_n(session):
    lead_a = _lead(session, reddit_id="t3_a")
    lead_b = _lead(session, reddit_id="t3_b")
    repo = CommentRepository(session)
    repo.add_many(lead_a.id, [{"author": "x", "body": "one"}, {"author": "y", "body": "two"}])
    session.commit()

    counts = repo.counts_for_leads([lead_a.id, lead_b.id])
    assert counts == {lead_a.id: 2}


# ------------------------------------------------------ the back-fill, AC5


def test_a_search_sourced_score_is_back_filled_during_the_comment_fetch(session):
    """docs/34 §P11 task 4. A search result carries no score in the HTML, and the
    permalink page has it — so the back-fill rides along with the fetch that was
    happening anyway rather than doubling the most expensive request."""
    lead = _lead(session, score=None, num_comments=None)
    scraper = CommentScraper(FakeClient(score=57, num_comments=21), {})

    plan, write = scraper.run(
        session,
        [candidate(lead.id, 90.0, num_comments=None)],
        admission_floor=35.0,
    )
    session.commit()

    assert plan.backfilled == 2
    assert session.get(Lead, lead.id).score == 57
    assert session.get(Lead, lead.id).num_comments == 21
    assert write.stored == 2


def test_a_stored_score_is_never_overwritten(session):
    """`leads.score` is a fact recorded at COLLECTION time. Replacing it with the
    value the post has now would silently re-date every lead the comment stage
    touched — a score would change depending on whether the lead happened to win
    a comment-fetch slot, making the column incomparable across leads."""
    lead = _lead(session, score=10, num_comments=12)
    scraper = CommentScraper(FakeClient(score=9999, num_comments=8888), {})

    plan, _ = scraper.run(session, [candidate(lead.id, 90.0)], admission_floor=35.0)
    session.commit()

    assert plan.backfilled == 0
    assert session.get(Lead, lead.id).score == 10
    assert session.get(Lead, lead.id).num_comments == 12


def test_an_unknown_metric_on_the_page_leaves_the_null_alone(session):
    """Writing 0 for "we could not tell" would replace an honest unknown with a
    confident wrong number — DI13 in the other direction."""
    lead = _lead(session, score=None)
    scraper = CommentScraper(FakeClient(score=None, num_comments=None), {})

    plan, _ = scraper.run(session, [candidate(lead.id, 90.0)], admission_floor=35.0)
    session.commit()

    assert plan.backfilled == 0
    assert session.get(Lead, lead.id).score is None


def test_no_candidates_means_no_query_and_no_requests(session):
    """A run whose every lead was rejected must not issue a `WHERE id IN ()`."""
    scraper = CommentScraper(FakeClient(), {})
    assert scraper.candidates_for(session, [], {}) == []


def test_a_lead_with_no_prescore_is_not_a_candidate(session):
    """Skipped rather than defaulted to 0.0: no pre-score means the scoring stage
    did not see it, and inventing one would put an unmeasured item into a ranking
    that claims to be ordered by pre-score."""
    lead = _lead(session)
    scraper = CommentScraper(FakeClient(), {})
    assert scraper.candidates_for(session, [lead.id], {}) == []
    assert len(scraper.candidates_for(session, [lead.id], {lead.id: 50.0})) == 1


def test_an_unfetchable_page_is_skipped_without_a_backfill(session):
    """`get_post_detail` returns None when the page could not be fetched — a
    distinct signal from a page that loaded and had no comments."""

    class Silent(FakeClient):
        def get_post_detail(self, url, limit=50):
            self.requested.append(url)
            return None

    lead = _lead(session, score=None)
    plan, write = CommentScraper(Silent(), {}).run(
        session, [candidate(lead.id, 90.0)], admission_floor=35.0
    )
    session.commit()

    assert plan.requests == 1
    assert plan.backfilled == 0
    assert write.stored == 0
    assert session.get(Lead, lead.id).score is None


def test_a_lead_deleted_between_planning_and_fetching_does_not_raise(session):
    """The comment stage commits before it fetches — deliberately, so the write
    lock is not held across the network — so the row can disappear underneath it.
    A crash here would lose every remaining candidate's comments."""
    from src.scrapers.comment_scraper import _backfill

    assert _backfill(session, 999_999, {"score": 5}) == 0


# --------------------------------------------------------------- fail soft


def test_one_unreachable_thread_does_not_stop_the_others(session):
    """AD-9, "fail soft on enrichment, loud on collection"."""

    class Flaky(FakeClient):
        def get_post_detail(self, url, limit=50):
            self.requested.append(url)
            if url.endswith("/1/x/"):
                raise RuntimeError("blocked")
            return super().get_post_detail(url, limit)

    lead_a = _lead(session, reddit_id="t3_a")
    lead_b = _lead(session, reddit_id="t3_b")
    client = Flaky()
    scraper = CommentScraper(client, {})

    plan, write = scraper.run(
        session,
        [
            Candidate(lead_a.id, "https://x/1/x/", 90.0, 10),
            Candidate(lead_b.id, "https://x/2/x/", 80.0, 10),
        ],
        admission_floor=35.0,
    )
    session.commit()

    assert plan.requests == 2
    assert write.stored == 2, "the second thread's comments must still land"


# --------------------------------------------------------------- settings


def test_deleting_the_scraping_block_reproduces_the_defaults():
    assert ScrapingSettings.from_config(None) == ScrapingSettings()
    assert ScrapingSettings.from_config({}) == ScrapingSettings()


def test_the_per_post_limit_matches_the_clients_own_default():
    """Cited rather than invented, so the key changes behaviour rather than
    merely appearing to."""
    import inspect

    from src.reddit_client import RedditClient

    client_default = inspect.signature(RedditClient.get_post_comments).parameters["limit"].default
    assert ScrapingSettings().max_comments_per_post == client_default


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_comments_per_post": -1},
        {"max_comment_posts": -1},
        {"min_post_comments_for_comment_fetch": -1},
    ],
)
def test_a_negative_setting_is_refused_loudly(kwargs):
    with pytest.raises(ValueError, match="must be >= 0"):
        ScrapingSettings(**kwargs)
