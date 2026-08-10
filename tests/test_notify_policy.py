"""P7 Stage 2 -- the deterministic notification policy.

No database, no network, no clock. Every test passes ``now`` explicitly, which is
what lets quiet hours be pinned at a boundary minute rather than at whatever time
the suite happens to run.

**Every policy row is driven by its own test**, not merely reached by one. P6's F1
is why the distinction is written down: coverage reported 87% on a file whose
branch nothing could reach, and only a surviving mutation found the defect. A row
that is executed as a side effect of testing something else is a row nobody has
actually made a claim about.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, time, timedelta, timezone

import pytest

from src.notify import (
    POLICY,
    QUIET_HOURS_EXEMPT,
    Decision,
    Kind,
    NotifySettings,
    decide,
    parse_quiet_window,
    quiet_hours,
)

# Midday and small hours, so a test that means "outside quiet hours" says so.
NOON = datetime(2026, 8, 10, 12, 0)
THREE_AM = datetime(2026, 8, 10, 3, 0)

ON = NotifySettings(enabled=True)
ON_QUIET = NotifySettings(enabled=True, quiet_window=(time(22, 0), time(7, 0)))


def call(kind, payload=None, *, settings=ON, now=NOON) -> Decision:
    return decide(kind, payload, settings=settings, now=now)


# ----------------------------------------------------------------- the five kinds


def test_every_kind_has_a_policy_row_and_no_row_is_orphaned():
    """The table is total over ``Kind`` and contains nothing else.

    ``decide`` indexes ``POLICY[resolved]`` without a fallback, so a kind added
    without a row would raise ``KeyError`` at the moment it first fired -- in
    production, on the run it was added to describe. This is the cheap version of
    finding that out.
    """
    assert set(POLICY) == set(Kind)
    assert len(POLICY) == 5, "freeze §7 fixes first delivery at five kinds"


def test_run_complete_notifies_when_leads_were_collected():
    d = call(Kind.RUN_COMPLETE, {"leads": 12})
    assert d.notify is True
    assert "12" in d.reason


def test_run_complete_notifies_with_zero_leads_when_a_subreddit_did_not_finish():
    """docs/22 §4.12's second clause: *"or the run failed"*.

    A run can reach COMPLETE having collected nothing *because* subreddits
    failed, which ``finalize_run`` already records as ``run.partial``. That is
    the one 0-lead run worth being told about.
    """
    assert call(Kind.RUN_COMPLETE, {"leads": 0, "subreddits_failed": 2}).notify is True
    assert call(Kind.RUN_COMPLETE, {"leads": 0, "subreddits_cancelled": 1}).notify is True


def test_run_complete_suppresses_a_clean_run_that_found_nothing():
    """Being told "0 leads" every night is how a channel gets muted."""
    d = call(Kind.RUN_COMPLETE, {"leads": 0})
    assert d.notify is False
    assert "cleanly" in d.reason


def test_run_failed_always_notifies():
    assert call(Kind.RUN_FAILED).notify is True
    assert call(Kind.RUN_FAILED, {}).notify is True


def test_gate_reached_always_notifies_and_names_the_gate():
    assert call(Kind.GATE_REACHED, {"gate": 1}).reason == "gate 1 is waiting for approval"
    # P17 has not produced gate numbers yet, so the field may be absent (C6).
    assert call(Kind.GATE_REACHED, {}).notify is True


def test_proxy_pool_degraded_notifies_only_when_a_degradation_was_recorded():
    """D2b. ``docs/22`` §4.12's *"healthy < 3"* would fire on every run forever.

    ``config.yaml`` ships no proxy file (P0 measured direct as better and
    recommended buying none), so the pool is legitimately empty and ``healthy``
    is 0 on every run. A level-based rule would be a permanent alarm about the
    design working as intended -- and an alert that always fires gets the whole
    tier switched off. The trigger is an event that happened.
    """
    assert call(Kind.PROXY_POOL_DEGRADED, {"degradations": 2}).notify is True

    quiet = call(Kind.PROXY_POOL_DEGRADED, {"degradations": 0})
    assert quiet.notify is False
    assert "no degradation" in quiet.reason

    # The shipped steady state: an empty pool, nothing having gone wrong.
    assert call(Kind.PROXY_POOL_DEGRADED, {"healthy": 0, "total": 0}).notify is False


def test_discovery_overflow_always_notifies_and_names_every_subreddit():
    """R19 -- overflow is an error, never a silent gap. G5 -- it is per-subreddit.

    Naming one subreddit when three overflowed would undo in the message exactly
    what P6 built in the data.
    """
    d = call(Kind.DISCOVERY_OVERFLOW, {"overflowed_subreddits": ["SaaS", "startups"]})
    assert d.notify is True
    assert "r/SaaS" in d.reason
    assert "r/startups" in d.reason

    # Still an alert with no list -- losing posts is not conditional on detail.
    assert call(Kind.DISCOVERY_OVERFLOW, {}).notify is True


def test_an_unknown_event_is_suppressed_and_no_model_is_consulted():
    """docs/22 §4.12's last row: *everything else -> Suppress*.

    The caller reads ``run_events``, where most rows are not notification kinds.
    Suppressing them is what makes the table **total**, which is what keeps R17
    absolute: there is no residual class left for a model to adjudicate.
    """
    for event in (
        "run.created",
        "discovery.poll.done",
        "lead.high_confidence",
        "",
        "budget.warning",
    ):
        d = call(event)
        assert d.notify is False, event
        assert "not a notification kind" in d.reason


def test_string_kinds_resolve_exactly_like_enum_members():
    """The dispatcher will pass ``run_events.event`` strings, not enum members."""
    assert call("run.failed").notify is True
    assert call("run.complete", {"leads": 3}).notify is True


# ------------------------------------------------------------------- the off switch


def test_disabled_suppresses_everything_including_the_exempt_kinds():
    """The rollback must be absolute.

    ``notify.enabled: false`` is the phase's documented rollback. A kind marked
    exempt from quiet hours must not leak past the off switch -- which is why
    ``decide`` checks ``enabled`` before it looks at the policy table at all.
    """
    off = NotifySettings(enabled=False)
    for kind in Kind:
        d = decide(kind, {"leads": 99, "degradations": 5}, settings=off, now=NOON)
        assert d.notify is False, kind
        assert "disabled" in d.reason


def test_defaults_are_off_and_the_transport_is_null():
    """Deleting the whole ``notify:`` block must reproduce these exactly."""
    for raw in (None, {}):
        s = NotifySettings.from_config(raw)
        assert s.enabled is False
        assert s.transport == "null"
        assert s.telegram_chat_id is None
        assert s.quiet_window is None


def test_from_config_reads_every_shipped_key():
    s = NotifySettings.from_config(
        {
            "enabled": True,
            "transport": "bot_api",
            "telegram_chat_id": 12345,
            "quiet_hours_utc": "22:00-07:00",
        }
    )
    assert s.enabled is True
    assert s.transport == "bot_api"
    assert s.telegram_chat_id == "12345", "a YAML int chat id must not stay an int"
    assert s.quiet_window == (time(22, 0), time(7, 0))


def test_min_confidence_alert_is_not_a_setting():
    """It would configure ``leads.confidence_score``, which arrives in 0006.

    P6's ``density_threshold`` note is the precedent: *"a key nothing reads is a
    documented capability that does not exist, so it is absent rather than
    ignored."* Accepting it here would let a later reader believe the threshold
    was being applied.
    """
    s = NotifySettings.from_config({"enabled": True, "min_confidence_alert": 85})
    assert not hasattr(s, "min_confidence_alert")
    assert "min_confidence_alert" not in set(NotifySettings.__dataclass_fields__)


# ------------------------------------------------------------------- quiet hours


def test_quiet_hours_suppress_the_routine():
    d = call(Kind.RUN_COMPLETE, {"leads": 4}, settings=ON_QUIET, now=THREE_AM)
    assert d.notify is False
    assert "quiet hours" in d.reason
    assert "4 lead(s)" in d.reason, "the reason must keep what it would have said"


def test_quiet_hours_never_suppress_a_failure():
    """docs/34 §P7 task 5. The 3 a.m. message you actually want."""
    assert call(Kind.RUN_FAILED, settings=ON_QUIET, now=THREE_AM).notify is True


def test_quiet_hours_never_suppress_an_overflow():
    """R19: an error held back until morning is the silent gap R19 forbids.

    ``budget.warning`` -- the second kind task 5 exempts -- is not shipped (D2),
    so its exemption has nothing to apply to and overflow takes the slot (D5).
    """
    payload = {"overflowed_subreddits": ["SaaS"]}
    assert call(Kind.DISCOVERY_OVERFLOW, payload, settings=ON_QUIET, now=THREE_AM).notify is True


def test_a_gate_is_not_exempt_from_quiet_hours():
    """A gate waits indefinitely by design -- AD-6, and ``runs`` has no expiry
    column -- so nothing is lost by it arriving after breakfast."""
    assert Kind.GATE_REACHED not in QUIET_HOURS_EXEMPT
    assert call(Kind.GATE_REACHED, {"gate": 1}, settings=ON_QUIET, now=THREE_AM).notify is False


def test_exempt_set_is_exactly_the_two_documented_kinds():
    assert set(QUIET_HOURS_EXEMPT) == {Kind.RUN_FAILED, Kind.DISCOVERY_OVERFLOW}


def test_outside_quiet_hours_nothing_is_suppressed():
    assert call(Kind.RUN_COMPLETE, {"leads": 4}, settings=ON_QUIET, now=NOON).notify is True


def test_no_quiet_window_means_nothing_is_ever_quiet():
    assert quiet_hours(None, THREE_AM) is False
    assert call(Kind.RUN_COMPLETE, {"leads": 1}, settings=ON, now=THREE_AM).notify is True


# ------------------------------------------------------- the window itself


WRAPPING = (time(22, 0), time(7, 0))
SAME_DAY = (time(9, 0), time(17, 0))


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (22, 0, True),  # start is inclusive
        (23, 59, True),
        (0, 0, True),  # across midnight
        (3, 0, True),
        (6, 59, True),
        (7, 0, False),  # end is exclusive
        (7, 1, False),
        (12, 0, False),
        (21, 59, False),
    ],
)
def test_a_wrapping_window_covers_the_night_and_both_boundaries(hour, minute, expected):
    """``22:00-07:00`` is two intervals on a clock face, not one.

    A naive ``start <= t < end`` is false for every minute of the night it is
    meant to cover. Both boundary minutes are pinned because an off-by-one here
    silences an alert for one minute a year -- a defect never found by reading.
    """
    assert quiet_hours(WRAPPING, datetime(2026, 8, 10, hour, minute)) is expected


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(8, False), (9, True), (16, True), (17, False), (18, False)],
)
def test_a_same_day_window_is_half_open_too(hour, expected):
    assert quiet_hours(SAME_DAY, datetime(2026, 8, 10, hour, 30 if hour == 16 else 0)) is expected


def test_a_window_with_equal_ends_is_empty_not_eternal():
    """``12:00-12:00`` silences nothing. The alternative -- reading it as "all
    day" -- would mute every routine alert from a setting that looks like a typo.
    """
    window = (time(12, 0), time(12, 0))
    assert quiet_hours(window, datetime(2026, 8, 10, 12, 0)) is False
    assert quiet_hours(window, THREE_AM) is False


def test_an_aware_datetime_is_converted_to_utc_rather_than_read_locally():
    """03:00 in a +05:00 zone is 22:00 UTC, which is inside ``22:00-07:00``.

    The codebase stores naive UTC, but a caller holding an aware value must not
    get a different answer than one holding the equivalent naive one.
    """
    aware = datetime(2026, 8, 10, 3, 0, tzinfo=timezone(timedelta(hours=5)))
    assert quiet_hours(WRAPPING, aware) is True
    assert quiet_hours(WRAPPING, datetime(2026, 8, 9, 22, 0)) is True
    assert quiet_hours(WRAPPING, datetime(2026, 8, 10, 3, 0, tzinfo=UTC)) is True


# --------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("22:00-07:00", (time(22, 0), time(7, 0))),
        ("09:30-17:45", (time(9, 30), time(17, 45))),
        ("22:00 - 07:00", (time(22, 0), time(7, 0))),
        ("  22:00-07:00  ", (time(22, 0), time(7, 0))),
        ("0:00-23:59", (time(0, 0), time(23, 59))),
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_parse_quiet_window_accepts_what_the_docstring_promises(raw, expected):
    assert parse_quiet_window(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "22:00",  # one time, not a window
        "22-07",  # no minutes
        "22:00-07:00 UTC",  # trailing rubbish
        "10pm-7am",
        "25:00-07:00",  # impossible hour
        "22:00-07:99",  # impossible minute
        "22:00--07:00",
        "nonsense",
        "22:00-07:00-09:00",
    ],
)
def test_a_malformed_quiet_window_is_rejected_loudly_at_load(raw):
    """Never silently ignored.

    A quiet-hours setting dropped because it was mistyped sends exactly the 3 a.m.
    message it was added to prevent, and the operator has no way to tell it was
    not applied. P6's F4: an unspecified constant is a decision -- so is a
    silently discarded one.
    """
    with pytest.raises(ValueError, match="quiet_hours_utc"):
        parse_quiet_window(raw)

    with pytest.raises(ValueError, match="quiet_hours_utc"):
        NotifySettings.from_config({"enabled": True, "quiet_hours_utc": raw})


# ----------------------------------------------------------------- payload robustness


@pytest.mark.parametrize("value", [None, "", "not a number", [], {}, object()])
def test_a_malformed_count_cannot_stop_an_alert(value):
    """A payload that arrived as JSON may carry anything.

    Counts coerce to 0 rather than raising, deliberately: a malformed payload
    must not be able to prevent a *failure* notification. The routine kinds
    degrade to their suppress branch, which is the safe direction for them.
    """
    assert call(Kind.RUN_FAILED, {"leads": value}).notify is True
    assert call(Kind.RUN_COMPLETE, {"leads": value}).notify is False
    assert call(Kind.PROXY_POOL_DEGRADED, {"degradations": value}).notify is False


def test_a_boolean_is_not_a_count():
    """``True`` is an ``int`` in Python, and ``int(True) == 1``.

    Without the explicit ``bool`` guard, ``{"leads": True}`` would read as one
    lead and send a message claiming a lead that does not exist.
    """
    assert call(Kind.RUN_COMPLETE, {"leads": True}).notify is False


def test_a_negative_count_does_not_become_a_notification():
    assert call(Kind.RUN_COMPLETE, {"leads": -5}).notify is False


def test_omitting_the_payload_entirely_is_safe_for_every_kind():
    for kind in Kind:
        assert isinstance(decide(kind, None, settings=ON, now=NOON), Decision), kind


# ------------------------------------------------------------------- purity


def test_decide_is_deterministic_over_repeated_calls():
    """Same inputs, same answer -- including the reason string.

    The reason is what an operator reads when asking why they were not told, so
    it is part of the contract rather than debug output.
    """
    args = (Kind.RUN_COMPLETE, {"leads": 7})
    first = call(*args, settings=ON_QUIET, now=THREE_AM)
    for _ in range(5):
        assert call(*args, settings=ON_QUIET, now=THREE_AM) == first


def test_decide_does_not_mutate_the_payload_it_is_given():
    payload = {"leads": 3, "subreddits_failed": 1}
    snapshot = dict(payload)
    call(Kind.RUN_COMPLETE, payload)
    assert payload == snapshot


def test_the_policy_reads_no_clock_of_its_own():
    """Every row is a function of its payload alone.

    If a rule consulted ``datetime.now()``, the same payload would decide
    differently at different times of day and the quiet-hours tests above would
    be testing two mechanisms at once.
    """
    for kind, rule in POLICY.items():
        payload = {"leads": 1, "degradations": 1, "gate": 1, "overflowed_subreddits": ["x"]}
        assert rule(payload) == rule(payload), kind


def test_decisions_are_frozen():
    d = Decision(True, "because")
    with pytest.raises(FrozenInstanceError):
        d.notify = False  # type: ignore[misc]


def test_a_decision_is_truthy_exactly_when_it_notifies():
    assert bool(Decision(True, "yes")) is True
    assert bool(Decision(False, "no")) is False
