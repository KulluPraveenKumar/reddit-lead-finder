"""Per-section validation — P14 task 3, and the isolation it exists to provide.

[34 §P14](../docs/34-implementation-plan.md)'s Acceptance row: *"a forced schema
failure in one section leaves the other 22 persisted"*. Every test below is
about that sentence, from a different angle.
"""

from __future__ import annotations

import pytest

from src.db.models import BKB_SECTION_KEYS, BKB_TYPED_SECTION_KEYS
from src.knowledge.sections import (
    SECTION_SPECS,
    STATUS_INCOMPLETE,
    STATUS_OK,
    PainPointOut,
    PersonaOut,
    validate_sections,
)


def _by_key(sections):
    return {s.key: s for s in sections}


# --------------------------------------------------------------- the registry


def test_all_twenty_three_sections_are_specified():
    """23 keys, 23 specs, and the same 23 — not merely the same count.

    A registry that agreed on the *number* while disagreeing on a *name* would
    make ``validate_sections`` return a verdict for a section nothing stores, and
    store nothing for a section that exists.
    """
    assert len(BKB_SECTION_KEYS) == 23
    assert tuple(SECTION_SPECS) == BKB_SECTION_KEYS


def test_the_typed_sections_are_exactly_the_three_the_check_constraint_names():
    """``ck_bkb_sections_payload_null_rule`` and the specs cannot disagree.

    If a fourth section were marked typed here, its payload would be written as
    ``NULL`` and the database would reject the row — and if one of the three were
    unmarked, the CHECK would reject it for carrying a payload. The failure is
    loud either way, which is exactly why it is worth pinning cheaply.
    """
    typed = {key for key, spec in SECTION_SPECS.items() if spec.typed}
    assert typed == set(BKB_TYPED_SECTION_KEYS)


def test_ideal_customer_profiles_is_not_typed():
    """05 §5.1b flags this exact mistake by name.

    An ICP *feels* structurally like a persona, so the instinct is to exempt it.
    There is **no `icps` table**, so its ``payload_json`` is the only copy of an
    ICP that exists and marking it typed would store ``NULL`` and lose the
    section entirely.
    """
    assert not SECTION_SPECS["ideal_customer_profiles"].typed
    assert SECTION_SPECS["ideal_customer_profiles"].model is not None


# ------------------------------------------------------------- the happy path


def test_a_well_formed_response_validates_all_twenty_three(bkb_payload):
    sections = validate_sections(bkb_payload)

    assert len(sections) == 23
    assert [s.key for s in sections] == list(BKB_SECTION_KEYS)
    assert all(s.status == STATUS_OK for s in sections), _by_key(sections)


def test_the_three_typed_sections_carry_no_payload_and_the_other_twenty_do(bkb_payload):
    """The biconditional the CHECK asserts, held by the value object itself.

    Building the row from :class:`ValidatedSection` therefore satisfies
    ``ck_bkb_sections_payload_null_rule`` **by construction** rather than by the
    writer remembering to.
    """
    for section in validate_sections(bkb_payload):
        if section.key in BKB_TYPED_SECTION_KEYS:
            assert section.payload is None, section.key
            assert section.items, f"{section.key} must still carry its typed items"
        else:
            assert section.payload is not None, section.key


def test_confidence_is_lifted_from_company_overview(bkb_payload):
    assert _by_key(validate_sections(bkb_payload))["company_overview"].confidence == 0.8


# ------------------------------------------------------- THE isolation property


def test_one_broken_section_leaves_the_other_twenty_two_intact(bkb_payload):
    """**The phase's acceptance criterion, stated as a test.**

    A slug that is not kebab-case fails ``PersonaOut``. If validation were done
    at the envelope, this single character would cost all 23 sections and two
    extra ``ai_calls`` rows on the repair ladder.

    ⚠ **The payload carries two personas and the assertion names the survivor,
    and both of those are deliberate.** Mutation **M3** — making
    ``_validate_items`` re-raise instead of collecting the failure — **survived**
    an earlier version of this test that asserted only ``status``, because
    ``_validate_one``'s outer ``except Exception`` backstop caught the escape and
    returned ``incomplete`` anyway. The status was identical; the *content* was
    not. Asserting the survivor is what separates *"the item loop handled it"*
    from *"the backstop swallowed the whole section"*.
    """
    bkb_payload["buyer_personas"].append(
        dict(bkb_payload["buyer_personas"][0], slug="ops-lead", name="Ops Lead")
    )
    bkb_payload["buyer_personas"][0]["slug"] = "Growth Lead"  # capitals and a space

    sections = validate_sections(bkb_payload)
    by_key = _by_key(sections)

    assert by_key["buyer_personas"].status == STATUS_INCOMPLETE
    assert "slug" in by_key["buyer_personas"].error
    assert [p.slug for p in by_key["buyer_personas"].items] == ["ops-lead"], (
        "the valid persona must survive its neighbour's bad slug"
    )

    others = [s for s in sections if s.key != "buyer_personas"]
    assert len(others) == 22
    assert all(s.status == STATUS_OK for s in others), [s.key for s in others if not s.ok]


def test_the_outer_backstop_is_a_backstop_and_not_the_working_path(bkb_payload):
    """``_validate_one``'s ``except Exception`` must never be what does the work.

    It exists so an *unforeseen* failure costs one section rather than 23 — but
    a section it handled has **lost all its content**, because the item loop
    never finished. Mutation M3 proved these two outcomes were indistinguishable
    to the suite. This is the test that distinguishes them: on the normal path a
    section with one bad entry keeps the rest, and the backstop cannot produce
    that.
    """
    bkb_payload["pain_points"][0]["severity"] = 99

    section = _by_key(validate_sections(bkb_payload))["pain_points"]
    assert section.status == STATUS_INCOMPLETE
    assert len(section.items) == 2, "the backstop would have left zero items here"
    assert "unexpected error" not in (section.error or "")


@pytest.mark.parametrize("key", list(BKB_SECTION_KEYS))
def test_any_single_section_can_be_destroyed_without_taking_the_others(bkb_payload, key):
    """The property above, over **every** section rather than a chosen one.

    A hand-picked example proves isolation for the case the author thought of.
    This proves it for all 23 — including the four bare string lists and the six
    single objects, whose failure modes are different from a typed list's.
    """
    bkb_payload[key] = {"totally": "wrong shape"} if key not in ("company_overview",) else 42

    sections = validate_sections(bkb_payload)
    by_key = _by_key(sections)

    assert by_key[key].status == STATUS_INCOMPLETE, key
    survivors = [s for s in sections if s.key != key]
    assert all(s.status == STATUS_OK for s in survivors), (
        f"breaking {key} also broke {[s.key for s in survivors if not s.ok]}"
    )


def test_validation_never_raises_even_on_a_hostile_payload():
    """Nothing this module is handed may escape as an exception.

    The input is a **model's** output. It is not adversarial, but it is not
    trustworthy either, and an exception here would take all 23 sections with
    it — which is the failure the phase exists to prevent.
    """
    for hostile in ({}, {"pain_points": None}, {"customer_language": "not a list"}):
        sections = validate_sections(hostile)
        assert len(sections) == 23


def test_an_empty_response_yields_twenty_three_incomplete_verdicts_not_a_short_list():
    """Absence is reported, never silently shortened.

    A caller that counted ``len(sections)`` and got 4 would have to know that
    meant "19 were missing". It always gets 23.
    """
    sections = validate_sections({})
    assert len(sections) == 23
    assert all("absent" in (s.error or "") for s in sections)


# ------------------------------------------------------------------- bounds


@pytest.mark.parametrize(
    ("key", "template", "too_few", "too_many"),
    [
        ("buyer_personas", "persona", 0, 6),
        ("pain_points", "pain", 2, 13),
        ("buying_signals", "signal", 2, 13),
        ("ideal_customer_profiles", "icp", 0, 4),
    ],
)
def test_the_stated_bounds_are_enforced_here_and_not_only_asked_for(
    bkb_payload, key, template, too_few, too_many
):
    """*"1–5 personas, 3–12 pains, 3–12 signals"* is a verdict, not a request.

    The prompt's Constraints block asks for these counts. A bound enforced only
    in a prompt is a **request**: the model complies most of the time and there
    is nothing to notice when it does not.
    """
    original = bkb_payload[key]

    bkb_payload[key] = [dict(original[0], slug=f"{template}-{i}") for i in range(too_few)]
    assert _by_key(validate_sections(bkb_payload))[key].status == STATUS_INCOMPLETE

    bkb_payload[key] = [dict(original[0], slug=f"{template}-{i}") for i in range(too_many)]
    section = _by_key(validate_sections(bkb_payload))[key]
    assert section.status == STATUS_INCOMPLETE
    assert "at most" in section.error


def test_a_section_at_its_exact_bound_is_accepted(bkb_payload):
    """The boundary itself is inside, not outside — an off-by-one here would
    reject a perfectly good five-persona response on every run."""
    persona = bkb_payload["buyer_personas"][0]
    bkb_payload["buyer_personas"] = [dict(persona, slug=f"persona-{i}") for i in range(5)]
    assert _by_key(validate_sections(bkb_payload))["buyer_personas"].status == STATUS_OK


# ------------------------------------------------------------------- slugs


def test_a_duplicate_slug_is_caught_before_it_reaches_a_unique_index(bkb_payload):
    """``ux_personas_project_slug`` is UNIQUE, so this must not reach the writer.

    Two rows with one slug would either raise at the database — losing the whole
    analysis — or silently overwrite the first, and **which of the two you get
    depends on the upsert**. Catching it here makes the outcome the same either
    way: the section is flagged, the first occurrence wins, and 22 sections are
    unaffected.
    """
    persona = bkb_payload["buyer_personas"][0]
    bkb_payload["buyer_personas"] = [persona, dict(persona, name="A Different Name")]

    section = _by_key(validate_sections(bkb_payload))["buyer_personas"]
    assert section.status == STATUS_INCOMPLETE
    assert "duplicate slug" in section.error
    assert len(section.items) == 1
    assert section.items[0].name == "Growth Lead", "the FIRST occurrence must win"


def test_the_surviving_duplicate_is_the_first_one_regardless_of_how_many_follow(bkb_payload):
    """Determinism: two runs over the same response must agree.

    Keeping the *last* would make the result depend on how many duplicates the
    model happened to emit.
    """
    persona = bkb_payload["buyer_personas"][0]
    bkb_payload["buyer_personas"] = [persona] + [dict(persona, name=f"n{i}") for i in range(4)]
    section = _by_key(validate_sections(bkb_payload))["buyer_personas"]
    assert [p.name for p in section.items] == ["Growth Lead"]


@pytest.mark.parametrize("bad", ["Growth Lead", "growth_lead", "growth--lead", "-growth", "GROWTH"])
def test_the_slug_pattern_refuses_every_near_miss(bad):
    with pytest.raises(ValueError, match="not a valid slug"):
        PersonaOut(slug=bad, name="x")


def test_an_optional_slug_field_accepts_none_but_not_rubbish(bkb_payload):
    """``outreach_angles.persona`` is nullable and still validated.

    A nullable field that skipped validation would be the quiet way a malformed
    slug got into a join key.
    """
    bkb_payload["outreach_angles"] = [{"angle": "no persona named"}]
    assert _by_key(validate_sections(bkb_payload))["outreach_angles"].status == STATUS_OK

    bkb_payload["outreach_angles"] = [{"persona": "Growth Lead", "angle": "x"}]
    assert _by_key(validate_sections(bkb_payload))["outreach_angles"].status == STATUS_INCOMPLETE


# ------------------------------------------------------------ strictness


def test_an_invented_field_flags_the_section_rather_than_being_ignored(bkb_payload):
    """``extra="forbid"``: drift is reported, not absorbed.

    A model quietly gaining a key means the prompt and the schema have parted
    company. Absorbing it lets that accumulate until something important goes
    missing.
    """
    bkb_payload["pain_points"][0]["invented_field"] = "surprise"
    section = _by_key(validate_sections(bkb_payload))["pain_points"]
    assert section.status == STATUS_INCOMPLETE
    assert "invented_field" in section.error


def test_only_the_offending_entry_is_dropped_from_a_list(bkb_payload):
    """One bad pain point costs one pain point, not the section's content.

    The same trade ``LeadAnalysisOut._check_slug_list`` already makes — and the
    ``incomplete`` status is what stops the drop from being invisible.
    """
    bkb_payload["pain_points"][1]["severity"] = 99  # outside 1..5
    section = _by_key(validate_sections(bkb_payload))["pain_points"]

    assert section.status == STATUS_INCOMPLETE
    assert len(section.items) == 2
    assert [p.slug for p in section.items] == ["attribution-gap", "tool-sprawl"]


def test_a_non_string_in_a_string_list_keeps_the_strings(bkb_payload):
    bkb_payload["customer_language"] = ["a real phrase", 7, None, "another"]
    section = _by_key(validate_sections(bkb_payload))["customer_language"]

    assert section.status == STATUS_INCOMPLETE
    assert section.payload == ["a real phrase", "another"]


def test_severity_and_frequency_are_bounded_one_to_five():
    """The columns default to 3 and P21 reads them as arithmetic (R6).

    An out-of-range severity would not raise at the database — both columns are
    plain integers — so this is the only place it is caught.
    """
    for value in (0, 6):
        with pytest.raises(ValueError):
            PainPointOut(slug="p", title="t", severity=value)
    assert PainPointOut(slug="p", title="t", severity=5).severity == 5
