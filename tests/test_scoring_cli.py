"""`python -m src.scoring` — the command the manual guide hands a non-developer.

docs/35 §1: *"if a step cannot be verified without reading code, the step is
wrong"*. P11 does put a funnel on the run page, but reaching it needs a full
orchestrated run against live Reddit; this command shows the **arithmetic** on
known input, so a wrong number can be attributed to the score rather than to the
network.

The commands here are the ones `docs/testing/P11-testing.md` prints. Executing
them in the suite is what stopped P10's guide shipping with a wrong `-k` filter
and what P9 had to correct after the fact.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from src.scoring.__main__ import DEMO, main


def run_cli(*args, capsys) -> str:
    assert main(list(args)) == 0
    return capsys.readouterr().out


def test_the_demo_corpus_shows_all_four_verdicts(capsys):
    """One run demonstrates the score doing all four of its jobs: a strong lead,
    a weak one under the floor, one caught by a hard filter, and one outside the
    window."""
    out = run_cli(capsys=capsys)
    assert "ADMIT" in out
    assert "below_prescore" in out
    assert "structural_noise" in out
    assert "out_of_window" in out


def test_it_prints_every_component_with_its_weight_and_contribution(capsys):
    """ "All components persisted" is the phase objective; a tester must be able
    to add the column up and reach the total."""
    out = run_cli(capsys=capsys)
    for component in (
        "keyword_tier",
        "keyword_density",
        "question_form",
        "recency",
        "engagement",
        "length",
    ):
        assert component in out
    assert "TOTAL" in out
    assert "/ 100" in out


def test_it_names_the_three_absent_components_and_their_phases(capsys):
    """Operator decision D1, made visible to the person running the command
    rather than buried in a docstring."""
    out = run_cli(capsys=capsys)
    assert "pain_phrase" in out
    assert "competitor" in out
    assert "subreddit_fit" in out
    assert "P12" in out and "P15" in out


def test_it_states_that_no_ai_call_was_made(capsys):
    """docs/34 §P11's bold criterion is "0 AI calls", and the guide's reader
    should not have to take that on trust from a document."""
    assert "AI calls made: 0" in run_cli(capsys=capsys)


BODY = "We are a small team and our spreadsheets are falling apart every month. " * 3


def test_a_single_title_and_body_can_be_scored(capsys):
    out = run_cli("Looking for a CRM - any recommendations?", "--body", BODY, capsys=capsys)
    assert "ADMIT" in out


def test_a_title_with_no_body_is_rejected_as_too_short(capsys):
    """`rules.min_chars: 80` measures a BODY, and P11 is the first phase to bind
    it to one — config.yaml has carried that note since P9.

    Worth its own test rather than a footnote: a tester running the command with
    a bare title gets a REJECT, and without this they would reasonably read it as
    the score being broken.
    """
    out = run_cli("Looking for a CRM - any recommendations?", capsys=capsys)
    assert "REJECT" in out
    assert "too_short" in out


def test_di25s_own_example_is_admitted(capsys):
    """The lead `triage.py` discarded live from P6 until P11. Printed by the
    manual guide so the operator sees the fix rather than reading about it."""
    out = run_cli(
        "Our hiring process is broken and I need a tool to fix it",
        "--body",
        "I am looking for any recommendations for something a small team can use. " * 3,
        "--score",
        "25",
        "--num-comments",
        "8",
        capsys=capsys,
    )
    assert "ADMIT" in out


def test_the_rollback_flag_scores_nothing_and_admits_everything(capsys):
    """The rollback, executable without editing config.yaml — the property P9's
    and P10's CLIs both provide for theirs."""
    out = run_cli("Weekly megathread", "--prescore-enabled", "false", capsys=capsys)
    assert "ADMIT" in out
    assert "prescore_disabled" in out


def test_the_admission_floor_can_be_moved_without_editing_the_config(capsys):
    """docs/06c §3.2's "tunable dial", made tunable for a tester.

    The fixture clears every hard filter, so the floor is the ONLY thing
    deciding — otherwise both runs reject for an unrelated reason and the test
    passes while proving nothing about the dial.
    """
    admitted = run_cli(
        "Weekly update on our tooling", "--body", BODY, "--admission-floor", "0", capsys=capsys
    )
    assert "ADMIT" in admitted

    rejected = run_cli(
        "Weekly update on our tooling", "--body", BODY, "--admission-floor", "100", capsys=capsys
    )
    assert "REJECT" in rejected
    assert "below_prescore" in rejected


def test_it_falls_back_to_shipped_defaults_when_no_config_can_be_read(capsys, monkeypatch):
    """The point of the command is to demonstrate the arithmetic; a tester
    running it from a directory without a config should still see a score."""
    import src.config

    monkeypatch.setattr(
        src.config, "load_config", lambda *a, **k: (_ for _ in ()).throw(OSError("no config"))
    )
    out = run_cli("Looking for a CRM - any recommendations?", "--body", BODY, capsys=capsys)
    assert "ADMIT" in out


def test_json_output_is_machine_readable(capsys):
    payload = json.loads(run_cli("--json", capsys=capsys))
    assert len(payload) == len(DEMO)
    assert {"title", "total", "decision", "components", "absent"} <= set(payload[0])
    assert 0.0 <= payload[0]["total"] <= 100.0


def test_a_file_of_posts_can_be_scored(tmp_path, capsys):
    path = tmp_path / "posts.json"
    path.write_text(
        json.dumps([{"title": "Looking for a CRM - any recommendations?", "body": "x" * 300}]),
        encoding="utf-8",
    )
    payload = json.loads(run_cli("--file", str(path), "--json", capsys=capsys))
    assert len(payload) == 1


def test_the_output_is_identical_across_runs(capsys):
    """The command pins `now`, so a guide can print an expected output that does
    not rot the next morning."""
    assert run_cli(capsys=capsys) == run_cli(capsys=capsys)


@pytest.mark.parametrize("args", [[], ["--json"], ["--prescore-enabled", "false"]])
def test_the_module_runs_as_a_subprocess_and_exits_zero(args):
    """`main()` returning 0 is not the same as `python -m src.scaring` working —
    the guide runs the latter, so the suite does too."""
    result = subprocess.run(
        [sys.executable, "-m", "src.scoring", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
