"""`python main.py feed` — the surface the manual guide is executed through.

Worth testing rather than trusting, for a reason that is easy to miss: the
manual guide asserts **exit codes**, and no other command in `main.py` has ever
returned a non-zero one. A `cmd_feed` that printed a friendly error and exited 0
would let guide steps T5 and T8 pass while reporting failure as success.

No network: every test drives the `--file` path or a stubbed client.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main

FIXTURES = Path(__file__).parent / "fixtures" / "atom"


def _run(args: list[str], config: dict | None = None):
    main.cmd_feed(config if config is not None else {}, ["feed", *args])


def test_a_saved_feed_is_read_and_counted(capsys):
    _run(["--file", str(FIXTURES / "listing_multireddit.xml")])
    out = capsys.readouterr().out
    assert "3 posts" in out
    assert "no network request" in out


def test_the_output_names_every_field_the_guide_checks(capsys):
    """The guide asks a non-developer to read specific values off the screen."""
    _run(["--file", str(FIXTURES / "listing_multireddit.xml")])
    out = capsys.readouterr().out
    assert "t3_a000101" in out
    assert "redditor_0023" in out and "/u/redditor_0023" not in out
    assert "r/SaaS" in out and "r/startups" in out
    assert "score: None" in out and "comments: None" in out


def test_limit_trims_the_file_path_too(capsys):
    _run(["--file", str(FIXTURES / "listing_100.xml"), "--limit", "10"])
    assert "10 posts" in capsys.readouterr().out


def test_a_malformed_feed_exits_non_zero_with_a_sentence(capsys):
    """Guide T5.

    An *unhandled* FeedParseError would also exit 1 — while printing a
    traceback. The exit code is not the whole assertion; the reader needs a
    sentence, not a stack.
    """
    with pytest.raises(SystemExit) as exc:
        _run(["--file", str(FIXTURES / "malformed.xml")])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Could not parse the feed" in out
    assert "Traceback" not in out


def test_an_empty_feed_exits_zero(capsys):
    """Guide T6. Empty is quiet; damaged is loud. The pair is the point."""
    _run(["--file", str(FIXTURES / "empty.xml")])
    assert "0 posts" in capsys.readouterr().out


def test_a_missing_file_reports_the_path_and_exits_non_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        _run(["--file", "no-such-feed.xml"])
    assert exc.value.code == 2


def test_no_subreddits_and_no_file_prints_usage(capsys):
    with pytest.raises(SystemExit) as exc:
        _run([])
    assert exc.value.code == 2
    assert "Usage" in capsys.readouterr().out


def test_the_off_switch_exits_non_zero(capsys):
    """Guide T8. Rollback level 1, seen from the operator's side."""
    with pytest.raises(SystemExit) as exc:
        _run(["--subreddits", "SaaS"], config={"discovery": {"rss_enabled": False}})
    assert exc.value.code == 1
    assert "disabled" in capsys.readouterr().out


def test_config_flag_loads_another_settings_file(tmp_path, capsys):
    """What keeps the guide's rollback test off the project's own config.yaml."""
    alt = tmp_path / "alt.yaml"
    alt.write_text(
        "subreddits:\n  - SaaS\n"
        "keywords:\n  high_intent:\n    - looking for\n"
        "scoring:\n  min_score: 0\n"
        "discovery:\n  rss_enabled: false\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        _run(["--config", str(alt), "--subreddits", "SaaS"])
    assert exc.value.code == 1


def test_config_flag_does_not_change_any_other_command():
    """`main()` still loads config exactly once, for every command.

    Restructuring that would have made `--config` global, which is a behaviour
    change to seven shipped commands in service of one new one.
    """
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert source.count("config = load_config()") == 1


def test_an_unknown_sort_is_reported_not_silently_accepted(capsys):
    """Reddit answers an unknown sort with the default and says nothing.

    `_feed_url` refuses before any request is made, so this reaches the CLI's
    error path without touching the network.
    """
    from src.net.egress import reset_policy

    try:
        with pytest.raises(SystemExit) as exc:
            _run(["--subreddits", "SaaS", "--sort", "sideways"])
        assert exc.value.code == 2
        assert "sort must be one of" in capsys.readouterr().out
    finally:
        # The policy is process-wide; a test that leaves one behind fails the
        # next test in a different file (PHASE-04-HANDOVER T4).
        reset_policy()
