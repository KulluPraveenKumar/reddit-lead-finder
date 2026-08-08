"""Stage 3 - metadata triage, and the request budget the policy has to hit.

Triage is a gate that discards items without ever seeing a body, so
[AD-10b](../docs/03-architecture.md) applies: every rejection carries a reason
from a closed vocabulary, and the caller stores it. These tests assert the
reason, not just the decision -- a gate that rejects for the wrong reason is
still a gate nobody can tune.
"""

from __future__ import annotations

import datetime

from src.discovery.policy import PolicyConfig, next_interval
from src.discovery.triage import REASONS, TriageConfig, triage
from src.discovery.watermarks import WatermarkState

NOW = datetime.datetime(2026, 8, 8, 12, 0, 0)
CFG = TriageConfig(keywords=("crm", "invoicing"), negative_terms=("nsfw",))


def post(title: str, *, author="example_user_1", days_old=1) -> dict:
    return {
        "id": "t3_aaa01",
        "title": title,
        "author": author,
        "subreddit": "SaaS",
        "body": "",
        "created_utc": NOW - datetime.timedelta(days=days_old),
    }


def test_an_ordinary_question_is_admitted():
    result = triage(post("Looking for a CRM that does not cost a fortune"), CFG, now=NOW)
    assert result.admitted
    assert result.reason is None


def test_keyword_hits_are_recorded_and_raise_the_provisional_score():
    plain = triage(post("Looking for something better"), CFG, now=NOW)
    matched = triage(post("Looking for a CRM with invoicing"), CFG, now=NOW)

    assert matched.total > plain.total
    assert matched.components["keyword_hits"] == ["crm", "invoicing"]


def test_a_missing_title_is_a_reason_not_an_exception():
    """A poll that dies on one bad entry loses the other ninety-nine."""
    result = triage({"id": "t3_x", "title": "", "author": "a"}, CFG, now=NOW)
    assert not result.admitted
    assert result.reason == "no_title"


def test_a_post_with_no_fields_at_all_does_not_raise():
    assert triage({}, CFG, now=NOW).reason == "no_title"


def test_bot_authors_are_rejected():
    for author in ("AutoModerator", "[deleted]", "RemindMeBot"):
        result = triage(post("A real question", author=author), CFG, now=NOW)
        assert not result.admitted, author
        assert result.reason == "bot_author"


def test_structural_rejections_name_which_pattern_fired():
    cases = {
        "[Hiring] Senior Python developer": "hiring",
        "Giveaway: three free licenses": "giveaway",
        "Weekly discussion thread": "megathread",
        "AMA: I built a SaaS in 30 days": "ama",
        "Upvote if you agree with this": "engagement_bait",
    }
    for title, expected in cases.items():
        result = triage(post(title), CFG, now=NOW)
        assert not result.admitted, title
        assert result.reason == expected, title


def test_a_post_outside_the_window_is_rejected():
    result = triage(post("Looking for a CRM", days_old=99), CFG, now=NOW)
    assert not result.admitted
    assert result.reason == "out_of_window"


def test_a_post_inside_the_window_is_kept():
    assert triage(post("Looking for a CRM", days_old=29), CFG, now=NOW).admitted


def test_negative_terms_are_rejected_and_recorded():
    result = triage(post("NSFW content roundup"), CFG, now=NOW)
    assert result.reason == "negative_term"
    assert result.components["negative_term"] == "nsfw"


def test_every_reason_produced_is_in_the_declared_vocabulary():
    """A closed vocabulary is what makes the funnel groupable in SQL."""
    titles = [
        "",
        "[Hiring] dev",
        "Giveaway time",
        "Weekly discussion thread",
        "AMA with me",
        "Upvote if you agree",
        "NSFW roundup",
        "Looking for a CRM",
    ]
    for title in titles:
        for days in (1, 99):
            result = triage(post(title, days_old=days), CFG, now=NOW)
            if result.reason is not None:
                assert result.reason in REASONS, result.reason

    result = triage(post("A question", author="AutoModerator"), CFG, now=NOW)
    assert result.reason in REASONS


def test_triage_never_reads_the_body():
    """The redesign's central claim: the decision costs no body fetch.

    Same post, opposite bodies, identical judgement. If this ever fails, stage 3
    has started depending on data stage 1 does not always carry, and the request
    arithmetic behind the whole phase stops holding.
    """
    with_body = post("Looking for a CRM")
    with_body["body"] = "a very long and persuasive description of a problem"
    without = post("Looking for a CRM")
    without["body"] = ""

    a, b = triage(with_body, CFG, now=NOW), triage(without, CFG, now=NOW)
    assert (a.decision, a.reason, a.total) == (b.decision, b.reason, b.total)


# --------------------------------------------------------------------------
# A3 - the request budget
# --------------------------------------------------------------------------


def test_steady_state_stays_within_eighty_requests_a_day():
    """A3 / D-AC4, simulated deterministically. No network.

    The scenario [28 §4](../docs/28-discovery-redesign.md) uses throughout: ten
    subreddits and twelve keywords. Listing discovery is **one** multireddit
    request per poll (U1 makes combining mandatory, not optional), and each
    keyword search is one request per poll.
    """
    cfg = PolicyConfig()
    day = datetime.timedelta(days=1)

    # A busy-but-typical channel: 20 posts/hour -> a 3-hour interval.
    listing = WatermarkState(observed_rate_per_hour=20.0)
    listing_polls = day / next_interval(listing, cfg)

    # Keyword channels are far quieter and back off on empty polls.
    keyword = WatermarkState(observed_rate_per_hour=2.0, consecutive_empty=2)
    keyword_polls = day / next_interval(keyword, cfg)

    total = listing_polls + (12 * keyword_polls)

    assert total <= 80, f"steady state would issue {total:.1f} requests/day"


def test_the_listing_channel_alone_cannot_exhaust_the_budget():
    """Even clamped to the 15-minute floor, one combined feed is 96/day.

    That is over 80 on its own, which is exactly why `min_interval` is a floor
    on a *combined* multireddit request rather than a per-subreddit one -- ten
    subreddits polled individually at the floor would be 960.
    """
    cfg = PolicyConfig()
    floor_polls = datetime.timedelta(days=1) / cfg.min_interval

    assert floor_polls == 96
    # ...and the budget therefore depends on the rate-driven interval, not the
    # floor. A 20 posts/hour subreddit lands at 8 polls/day.
    assert (
        datetime.timedelta(days=1) / next_interval(WatermarkState(observed_rate_per_hour=20.0), cfg)
        == 8
    )


# --------------------------------------------------------------------------
# A4 - cold start coverage
# --------------------------------------------------------------------------


def test_the_feed_window_is_at_least_as_wide_as_the_html_walk():
    """A4 / D-AC5, the half that *can* be checked without a network.

    ⚠️ **This is not the acceptance criterion.** D-AC5 says "cold start collects
    >= 95% of what the HTML design collects", and proving that needs two
    captures of the same subreddit at the same instant. It is a **live**
    measurement and it lives in the manual guide.

    An earlier version of this test compared a set of synthetic ids with itself
    and asserted 100% coverage. It could not fail, which makes it documentation
    wearing a test's clothes -- P5's F3, and the reason its handover says a
    guard that cannot fail is worse than an absent one. It was deleted rather
    than adjusted.

    What is genuinely checkable offline is the *arithmetic that makes the claim
    plausible*: the current HTML design walks four listing pages at 25 posts
    each, and one feed request returns up to 100. If the feed ceiling ever fell
    below the HTML walk's reach, the criterion could not hold at any coverage
    and this fails first.
    """
    from src.reddit_client import DEFAULT_FEED_LIMIT, MAX_PAGES

    html_reach = MAX_PAGES * 25
    assert min(html_reach, 100) <= DEFAULT_FEED_LIMIT, (
        f"one feed request reaches {DEFAULT_FEED_LIMIT} posts but the HTML walk "
        f"reaches {html_reach}; cold-start parity cannot hold"
    )
