"""``python -m src.dedupe`` — the only thing in P10 a non-developer can look at.

[35 §1] requires the manual guide to be executable without reading code. P10 adds
no page, no endpoint and no row, so this CLI *is* the guide's instrument — which
makes it load-bearing, and which is why it is tested rather than left as a
convenience script. Every command in ``docs/testing/P10-testing.md`` is asserted
here, so a guide step that would print the wrong thing fails in CI rather than in
front of the operator. That is P9's own correction: two of its manual steps
promised output the code did not produce, and the fix landed in ``defa9ca``.
"""

from __future__ import annotations

import json

import pytest

from src.dedupe.__main__ import DEMO, main


def test_the_demo_runs_and_groups_the_three_crm_posts(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "4 posts -> 1 group(s)" in out
    assert "collapse rate 50%" in out
    assert "representative -> enriched" in out


def test_the_demo_leaves_the_unrelated_post_alone(capsys):
    """A demo that grouped everything would demonstrate nothing."""
    main([])
    assert "ungrouped: #4" in capsys.readouterr().out


def test_the_demo_reports_each_duplicates_own_reason(capsys):
    """#2 is an exact repost; #3 differs by one word. They must not read alike."""
    main([])
    out = capsys.readouterr().out
    assert "duplicate -> duplicate_exact" in out
    assert "duplicate -> duplicate_near" in out


def test_the_minhash_rollback_is_visible_from_the_command_line(capsys):
    """The manual guide's rollback step. ``--minhash-enabled false`` must both
    say it is off and produce a smaller collapse."""
    assert main(["--minhash-enabled", "false"]) == 0
    out = capsys.readouterr().out
    assert "minhash=OFF (rollback state)" in out
    assert "collapse rate 25%" in out


def test_the_exact_rollback_is_visible_from_the_command_line(capsys):
    assert main(["--exact-enabled", "false", "--minhash-enabled", "false"]) == 0
    out = capsys.readouterr().out
    assert "exact=OFF (rollback state)" in out
    assert "0 group(s)" in out


def test_the_header_reports_the_settings_actually_in_use(capsys):
    main([])
    out = capsys.readouterr().out
    assert "jaccard>=0.85" in out
    assert "semantic=off" in out


def test_show_hashes_prints_a_hash_for_every_post_including_ungrouped_ones(capsys):
    main(["--show-hashes"])
    out = capsys.readouterr().out
    assert "content hashes" in out
    for row in DEMO:
        assert f"#{row['id']}" in out


def test_a_json_file_of_posts_can_be_supplied(tmp_path, capsys):
    path = tmp_path / "posts.json"
    path.write_text(
        json.dumps(
            [
                {"id": 1, "title": "Which CRM?", "body": "Small team of five.", "score": 5},
                {"id": 2, "title": "**Which CRM?**", "body": "Small team of five.", "score": 1},
            ]
        ),
        encoding="utf-8",
    )
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "2 posts -> 1 group(s)" in out


def test_a_post_with_missing_optional_fields_is_accepted(tmp_path, capsys):
    """An operator hand-writing the JSON will omit ``score`` and probably ``body``."""
    path = tmp_path / "sparse.json"
    path.write_text(json.dumps([{"id": 1, "title": "Only a title"}]), encoding="utf-8")
    assert main([str(path)]) == 0
    assert "1 posts -> 0 group(s)" in capsys.readouterr().out


def test_the_demo_corpus_is_the_shape_the_guide_describes():
    """Four posts: an exact pair, a near-duplicate, and one unrelated control."""
    assert len(DEMO) == 4
    assert {row["id"] for row in DEMO} == {1, 2, 3, 4}


def test_an_unreadable_file_fails_loudly_rather_than_silently_grouping_nothing():
    with pytest.raises(FileNotFoundError):
        main(["no-such-file.json"])
