"""The ``dedup:`` block — defaults, validation, and the rollback-by-deletion property.

Modelled on ``test_rules_settings.py``. The property that matters most is the one
P9, P7 and P5 all documented for their own blocks: **deleting the whole block
reproduces the shipped defaults exactly**, so a rollback by deletion behaves
identically to a rollback by flag.

⚠️ P9's trap **T5** applies to every test in this file: a survivor can be a *test*
defect rather than a code defect. P9's mutation M25 survived because every test
used the default value of the setting it was checking — *the settings were plumbed
and nothing proved the plumbing carried anything*. So each key here is asserted
with a **non-default** value reaching the behaviour it controls, not merely
reaching the dataclass.
"""

from __future__ import annotations

import pytest
import yaml

from src.dedupe import DedupItem, DedupSettings
from src.dedupe.groups import build_groups
from src.dedupe.minhash import shingles

BODY = (
    "our spreadsheets are falling apart and we need a real crm tool for a team of "
    "five people. we have tried a few free options but none of them handle repeat "
    "customers properly and the reporting is useless."
)


# ------------------------------------------------------------- defaults


def test_the_shipped_defaults_are_06c_section_4_2s_constants():
    """Cited, not invented: ``SHINGLE_K = 5``, ``NUM_PERM = 128``, ``LSH_THRESH = 0.85``."""
    settings = DedupSettings()
    assert settings.shingle_k == 5
    assert settings.num_perm == 128
    assert settings.jaccard_threshold == 0.85


def test_both_deterministic_tiers_are_on_by_default():
    """``false`` is the rollback state, not the resting state — P9's reasoning
    for ``rules_enabled``, applied to the same shape of key."""
    assert DedupSettings().exact_enabled is True
    assert DedupSettings().minhash_enabled is True


def test_the_semantic_tier_is_off_by_default():
    """P0 measured neither ``model2vec`` nor ``sqlite_vec`` installed, so an
    on-by-default tier 3 would be off in practice on every host anyway — and a
    default that lies about what runs is worse than one that does not."""
    assert DedupSettings().semantic_threshold is None


@pytest.mark.parametrize("config", [None, {}, {"dedup": None}, {"dedup": {}}, {"other": {}}])
def test_deleting_the_block_reproduces_the_defaults_exactly(config):
    """Rollback by deletion == rollback by flag. The property the ``rules:``,
    ``notify:`` and ``discovery:`` blocks each document for themselves."""
    assert DedupSettings.from_config(config) == DedupSettings()


def test_an_unknown_key_is_ignored_rather_than_fatal():
    """A config that refused to load because of a stray key would turn a typo
    into an outage."""
    assert DedupSettings.from_config({"dedup": {"shingle_k": 7, "typo": 1}}).shingle_k == 7


def test_an_explicit_null_and_an_absent_key_both_mean_off():
    assert (
        DedupSettings.from_config({"dedup": {"semantic_threshold": None}}).semantic_threshold
        is None
    )
    assert DedupSettings.from_config({"dedup": {}}).semantic_threshold is None


def test_a_configured_semantic_threshold_is_read_as_a_float():
    assert (
        DedupSettings.from_config({"dedup": {"semantic_threshold": 0.88}}).semantic_threshold
        == 0.88
    )


# ------------------------------------------------------------ validation


@pytest.mark.parametrize("value", [0, -1])
def test_a_shingle_width_below_one_is_refused(value):
    with pytest.raises(ValueError, match="shingle_k must be >= 1"):
        DedupSettings(shingle_k=value)


@pytest.mark.parametrize("value", [0, -5])
def test_a_signature_width_below_one_is_refused(value):
    with pytest.raises(ValueError, match="num_perm must be >= 1"):
        DedupSettings(num_perm=value)


@pytest.mark.parametrize("value", [-0.1, 1.1, 2.0])
def test_a_jaccard_threshold_outside_zero_to_one_is_refused(value):
    """It is a *similarity*, and a threshold of 2.0 would silently disable the
    tier while the config still claimed it was on."""
    with pytest.raises(ValueError, match="must be in \\[0, 1\\]"):
        DedupSettings(jaccard_threshold=value)


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_a_semantic_threshold_outside_zero_to_one_is_refused(value):
    with pytest.raises(ValueError, match="cosine similarity"):
        DedupSettings(semantic_threshold=value)


# ------------------------- each key actually reaches the behaviour (T5)


def test_shingle_k_changes_what_gets_shingled():
    """T5: proving the setting is *carried*, not merely stored."""
    settings = DedupSettings.from_config({"dedup": {"shingle_k": 3}})
    assert settings.shingle_k == 3
    assert shingles("abcdef", settings.shingle_k) == {"abc", "bcd", "cde", "def"}


def test_num_perm_changes_the_signature_width_that_is_produced():
    from src.dedupe.minhash import signature

    settings = DedupSettings.from_config({"dedup": {"num_perm": 64}})
    sig = signature(shingles("which crm should i use for a small team"), settings.num_perm)
    assert len(sig) == 64


def test_jaccard_threshold_changes_which_pairs_group():
    """The pair below is near 0.86: it groups at the default and not at 0.99."""
    items = [
        DedupItem(("lead", 1), "Which CRM?", BODY),
        DedupItem(("lead", 2), "Which CRM?", BODY.replace("five people", "six people")),
    ]
    assert build_groups(items, DedupSettings(jaccard_threshold=0.85)).groups
    assert build_groups(items, DedupSettings(jaccard_threshold=0.99)).groups == ()


def test_exact_enabled_false_changes_the_outcome_not_just_the_flag():
    items = [
        DedupItem(("lead", 1), "Which CRM?", BODY),
        DedupItem(("lead", 2), "**Which CRM?**", BODY),
    ]
    on = build_groups(items, DedupSettings(exact_enabled=True, minhash_enabled=False))
    off = build_groups(items, DedupSettings(exact_enabled=False, minhash_enabled=False))
    assert len(on.groups) == 1
    assert off.groups == ()


def test_minhash_enabled_false_changes_the_outcome_not_just_the_flag():
    items = [
        DedupItem(("lead", 1), "Which CRM?", BODY),
        DedupItem(("lead", 2), "Which CRM?", BODY.replace("five people", "six people")),
    ]
    assert build_groups(items, DedupSettings(minhash_enabled=True)).groups
    assert build_groups(items, DedupSettings(minhash_enabled=False)).groups == ()


# ------------------------------------------------------ the shipped file


def test_the_shipped_config_parses_into_the_shipped_defaults():
    """``config.yaml`` is committed, and a block that disagreed with the code's
    defaults would make the documentation wrong in the one place an operator
    looks first."""
    from pathlib import Path

    raw = yaml.safe_load(
        Path(__file__).resolve().parents[1].joinpath("config.yaml").read_text(encoding="utf-8")
    )
    assert DedupSettings.from_config(raw) == DedupSettings()


def test_the_shipped_config_ships_the_semantic_tier_off():
    """If this ever fails, a host without ``model2vec`` is running a tier that
    silently contributes nothing while the config says it is on."""
    from pathlib import Path

    raw = yaml.safe_load(
        Path(__file__).resolve().parents[1].joinpath("config.yaml").read_text(encoding="utf-8")
    )
    assert raw["dedup"]["semantic_threshold"] is None
