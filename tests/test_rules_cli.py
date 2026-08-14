"""`python -m src.rules` — the demo the manual guide is built on.

Stage 4 shipped it untested, which the Stage 5 coverage check found: every other
module under `src/rules/` was at 100% and this one at 0%. It matters more than a
convenience script usually would, because **docs/testing/P09-testing.md's T2, T3
and T4 are this module's output**. A guide whose expected text drifts from the
program is the DI19 failure, and nothing was pinning the text.
"""

from __future__ import annotations

import pytest

from src.rules.__main__ import main

MEGATHREAD = "Weekly megathread - ask your questions here"


def _run(capsys, argv):
    code = main(argv)
    return code, capsys.readouterr().out


# ----------------------------------------------------------- the guide's cases


def test_a_megathread_is_rejected_with_its_reason(capsys):
    """T2's first command. The wording here IS the guide's expected output."""
    code, out = _run(capsys, [MEGATHREAD])
    assert code == 0
    assert "rules: on" in out
    assert "reject · structural_noise · megathread" in out


def test_a_hiring_ad_is_rejected(capsys):
    """T2's second command."""
    _, out = _run(capsys, ["[HIRING] Senior Python developer, remote"])
    assert "reject · structural_noise · hiring" in out


def test_a_genuine_question_is_admitted(capsys):
    """T2's third command."""
    _, out = _run(capsys, ["Looking for a tool to track competitor pricing"])
    assert "admit" in out
    assert "reject" not in out


def test_the_hiring_near_miss_is_admitted(capsys):
    """⚠️ T3 — the test that matters most in the guide.

    If this ever prints `reject`, the filter is discarding real customers who
    happen to use a common word, and nothing else in the system would report it.
    """
    _, out = _run(capsys, ["Our hiring process is broken and I need a tool to fix it"])
    assert "admit" in out


# --------------------------------------------------------------- the rollback


def test_the_rules_enabled_override_turns_the_rules_off(capsys):
    """T4. The override exists so a non-developer never edits config.yaml —
    a Notepad-added BOM there breaks every command in the project."""
    _, out = _run(capsys, ["--rules-enabled", "false", MEGATHREAD])
    assert "OFF (rollback state)" in out
    assert "admit" in out


def test_the_override_can_also_force_the_rules_on(capsys):
    _, out = _run(capsys, ["--rules-enabled", "true", MEGATHREAD])
    assert "rules: on" in out
    assert "reject · structural_noise · megathread" in out


def test_the_rollback_is_reversible_within_one_session(capsys):
    """Off then on, proving the override holds no state."""
    _, off = _run(capsys, ["--rules-enabled", "false", MEGATHREAD])
    _, on = _run(capsys, ["--rules-enabled", "true", MEGATHREAD])
    assert "admit" in off
    assert "reject" in on


# ------------------------------------------------------------- other options


def test_an_author_can_be_judged(capsys):
    _, out = _run(capsys, ["--author", "WikiTextBot", "a perfectly ordinary title"])
    assert "reject · bot_or_deleted · known_bot" in out


def test_a_body_exercises_the_length_rule(capsys):
    _, out = _run(capsys, ["--body", "tiny", "a perfectly ordinary title"])
    assert "reject · too_short" in out


def test_the_settings_line_reports_min_chars(capsys):
    """The guide tells a tester to expect this line; it must actually appear."""
    _, out = _run(capsys, [MEGATHREAD])
    assert "min_chars=" in out


# ------------------------------------------------------------------- argparse


def test_a_missing_title_exits_rather_than_traces_back(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2  # argparse's usage error


def test_an_invalid_rules_enabled_value_is_rejected():
    with pytest.raises(SystemExit) as exc:
        main(["--rules-enabled", "maybe", MEGATHREAD])
    assert exc.value.code == 2
