"""The `rules:` / `pipeline:` blocks, and the rollback they make executable.

`pipeline.rules_enabled: false` is P9's documented rollback, and
EXECUTION_MODE_LOCK section 4 requires a rollback be *executed and verified*,
not merely documented. P9 wires no call site, so a flag read by anything else
would have nothing to disable — which is why `src/rules/` reads it itself
(operator decision D4).
"""

from __future__ import annotations

import pytest
import yaml

from src.rules import RulesSettings, evaluate
from src.rules.structural import check_structural
from tests.test_boundaries import PROJECT_ROOT

MEGATHREAD = "Weekly megathread - ask your questions here"


# ------------------------------------------------------------------ defaults


def test_absent_blocks_reproduce_the_defaults_exactly():
    """A rollback by deletion must behave identically to a rollback by flag."""
    assert RulesSettings.from_config({}) == RulesSettings()
    assert RulesSettings.from_config(None) == RulesSettings()
    assert RulesSettings.from_config({"unrelated": {"x": 1}}) == RulesSettings()


def test_the_shipped_defaults_are_the_documented_ones():
    s = RulesSettings()
    assert s.enabled is True
    assert s.min_chars == 80  # docs/06b, cited rather than invented
    assert s.skip_deleted_authors is True
    assert s.skip_bot_authors is True


def test_an_unknown_key_is_ignored_rather_than_rejected():
    """A config that refused to load on a typo would turn it into an outage."""
    s = RulesSettings.from_config({"rules": {"min_chars": 40, "nonsense": True}})
    assert s.min_chars == 40


def test_settings_are_read_from_both_blocks():
    """34 §P9 puts the keys in two blocks, so from_config takes the whole config."""
    s = RulesSettings.from_config(
        {"pipeline": {"rules_enabled": False}, "rules": {"min_chars": 10}}
    )
    assert s.enabled is False
    assert s.min_chars == 10


# ------------------------------------------------- the block actually ships


def test_the_rules_and_pipeline_blocks_ship_in_config_yaml():
    """A default nothing reads is a documented capability that does not exist."""
    raw = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert "pipeline" in raw, "docs/34 §P9's Rollback row requires pipeline.rules_enabled"
    assert "rules" in raw, "docs/34 §P9's Config row requires the rules block"

    shipped = RulesSettings.from_config(raw)
    assert shipped == RulesSettings(), (
        "the shipped block must equal the defaults, so deleting it changes nothing"
    )


def test_the_shipped_config_enables_the_rules():
    """`false` is the rollback state, not the resting state."""
    raw = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert raw["pipeline"]["rules_enabled"] is True


# --------------------------------------------------------------- the rollback


def test_the_engine_rejects_when_enabled():
    result = evaluate(title=MEGATHREAD, settings=RulesSettings(enabled=True))
    assert result.rejected
    assert result.detail == "megathread"


def test_the_engine_admits_everything_when_disabled():
    """⚠️ Mutation M16 — a rule that ignores its own off switch."""
    result = evaluate(title=MEGATHREAD, settings=RulesSettings(enabled=False))
    assert not result.rejected
    assert result.reason is None


@pytest.mark.parametrize(
    ("title", "author", "text"),
    [
        (MEGATHREAD, None, None),
        ("[HIRING] dev", None, None),
        ("a fine title", "WikiTextBot", None),
        ("a fine title", None, "tiny"),
    ],
)
def test_nothing_is_rejected_when_disabled_whatever_the_input(title, author, text):
    """Every rejecting path, proved to be off — not just the first one."""
    off = RulesSettings(enabled=False)
    assert not evaluate(title=title, author=author, text=text, settings=off).rejected
    # …and each of them really does reject when the flag is on.
    on = RulesSettings(enabled=True)
    assert evaluate(title=title, author=author, text=text, settings=on).rejected


def test_disabling_short_circuits_before_any_rule_runs(monkeypatch):
    """Not merely "returns admitted" — the regexes must not execute at all.

    A disabled engine that still evaluated every pattern would be a rollback in
    name only: the cost the flag exists to remove would still be paid.
    """
    import src.rules.structural as structural

    called = False

    def explode(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("check_structural ran while the rules were disabled")

    monkeypatch.setattr(structural, "check_structural", explode)
    assert not evaluate(title=MEGATHREAD, settings=RulesSettings(enabled=False)).rejected
    assert called is False


# --------------------------------------------- settings reach the rules

# ⚠️ These four exist because mutation M25 SURVIVED without them.
#
# Replacing `skip_bot_authors=cfg.skip_bot_authors` with a hardcoded `True`
# inside `evaluate` left the whole suite green: every test either used the
# default (True, so indistinguishable) or disabled the engine entirely. The
# settings were plumbed and nothing proved the plumbing carried anything.
#
# That is the "masked assertion" class PHASE-08-HANDOVER §4 T5 records — a
# survivor that was a real test defect rather than an equivalence.


def test_skip_bot_authors_false_reaches_the_author_rule():
    settings = RulesSettings(skip_bot_authors=False)
    assert not evaluate(title="a fine title", author="WikiTextBot", settings=settings).rejected
    assert not evaluate(title="a fine title", author="MyBot", settings=settings).rejected
    # …and the same input with the default setting is rejected.
    assert evaluate(title="a fine title", author="WikiTextBot").rejected


def test_skip_deleted_authors_false_reaches_the_author_rule():
    settings = RulesSettings(skip_deleted_authors=False)
    assert not evaluate(title="a fine title", author="[deleted]", settings=settings).rejected
    assert evaluate(title="a fine title", author="[deleted]").rejected


def test_min_chars_reaches_the_length_rule():
    short = "tiny"
    assert evaluate(title="a fine title", text=short).rejected
    assert not evaluate(
        title="a fine title", text=short, settings=RulesSettings(min_chars=2)
    ).rejected


def test_the_two_author_flags_are_independent_through_the_engine():
    only_bots_off = RulesSettings(skip_bot_authors=False)
    only_deleted_off = RulesSettings(skip_deleted_authors=False)
    assert evaluate(title="t", author="[deleted]", settings=only_bots_off).rejected
    assert evaluate(title="t", author="MyBot", settings=only_deleted_off).rejected


# ------------------------------------------------------------- the engine


def test_the_engine_returns_the_first_rejection_not_the_last():
    """Author is checked before structure: cheapest and most certain first."""
    result = evaluate(title="[HIRING] dev", author="[deleted]")
    assert result.detail == "deleted"


def test_the_length_rule_is_skipped_when_no_text_is_supplied():
    """P9's callers see titles; nothing binds min_chars to a body until P11."""
    assert not evaluate(title="a perfectly ordinary title").rejected


def test_the_length_rule_applies_when_text_is_supplied():
    result = evaluate(title="a perfectly ordinary title", text="tiny")
    assert result.rejected
    assert result.reason == "too_short"


def test_negative_terms_see_the_body_when_one_is_supplied():
    result = evaluate(title="a clean title", text="this mentions spam", negative_terms=["spam"])
    assert result.rejected
    assert result.reason == "negative_term"


def test_the_default_settings_are_used_when_none_are_passed():
    assert evaluate(title=MEGATHREAD).rejected
    assert check_structural(MEGATHREAD).rejected
