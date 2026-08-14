"""``python -m src.dedupe`` — run the cascade over a file of posts and show the groups.

**P10 adds no page, no endpoint and no database row a person can look at**, for
the same reason P9 did not: [34 §P10](../../docs/34-implementation-plan.md)'s
Files row is a library, and P11 is its first caller.
[35 §1](../../docs/35-testing-strategy.md) requires the manual guide to be
executable by a non-developer — *"if a step cannot be verified without reading
code, the step is wrong"* — so without this module the guide would be a list of
pytest invocations, which is exactly what that rule forbids.

Outside the Files row, which [34 §1.1](../../docs/34-implementation-plan.md)
calls *"a guide, not a contract"*. P5's ``feed`` CLI, P6's ``triage.py`` and P9's
``python -m src.rules`` are the precedents.

Input is a small JSON list, so the manual guide can hand a non-developer a file
rather than a Python session::

    [
      {"id": 1, "title": "Which CRM should I use?", "body": "Small team..."},
      {"id": 2, "title": "**Which CRM should I use?**", "body": "Small team..."}
    ]

⚠️ **Imports nothing from ``src.ai``**, and fence 2 covers it automatically
because it lives under ``src/dedupe/``. A convenience script is exactly where a
boundary quietly leaks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import KIND_LEAD, DedupItem, DedupSettings
from .exact import content_hash
from .groups import build_groups

#: A worked corpus, used when no file is given. Four posts: two byte-different
#: spellings of one discussion, one near-duplicate of it, and one unrelated post
#: that must stay alone -- so a single run demonstrates both that grouping
#: happens and that it does not over-reach.
DEMO: list[dict[str, Any]] = [
    {
        "id": 1,
        "title": "Which CRM should I use?",
        "body": "Five person team and our spreadsheets are falling apart. Budget is small.",
        "score": 10,
    },
    {
        "id": 2,
        "title": "**Which CRM should I use?**",
        "body": (
            "Five person team and our spreadsheets are falling apart. Budget is small."
            "\n\nEDIT: thanks everyone, going with the first suggestion"
        ),
        "score": 3,
    },
    {
        "id": 3,
        "title": "Which CRM should I use?",
        "body": "Five person team and our spreadsheets are falling apart. Budget is tight.",
        "score": 7,
    },
    {
        "id": 4,
        "title": "Best deep dish pizza in Chicago?",
        "body": "Visiting next week for a birthday dinner. Where should we book?",
        "score": 99,
    },
]


def _load_config() -> dict[str, Any]:
    """The real ``config.yaml``, or empty defaults if it cannot be read.

    A demo that refused to run because the config was missing would be a worse
    diagnostic than one that says which settings it used. P9's CLI took the same
    line.
    """
    try:
        from src.config import load_config

        return load_config() or {}
    except Exception as exc:  # pragma: no cover - exercised by hand, not in CI
        print(f"note: could not read config.yaml ({exc}); using defaults", file=sys.stderr)
        return {}


def _to_items(raw: list[dict[str, Any]]) -> list[DedupItem]:
    return [
        DedupItem(
            key=(KIND_LEAD, int(row["id"])),
            title=str(row.get("title") or ""),
            body=str(row.get("body") or ""),
            score=row.get("score"),
        )
        for row in raw
    ]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.dedupe",
        description="Group near-identical posts with the deterministic dedup cascade.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="a JSON file of posts with id/title/body/score. Omit for the built-in demo.",
    )
    parser.add_argument(
        "--minhash-enabled",
        choices=("true", "false"),
        default=None,
        help=(
            "override dedup.minhash_enabled without editing config.yaml. This is how "
            "the manual guide demonstrates the rollback: editing the file by hand risks "
            "a Notepad-added BOM, after which every command in the project fails with "
            "'Missing required config key: subreddits' -- which reads as a defect in "
            "this phase and is not one."
        ),
    )
    parser.add_argument(
        "--exact-enabled",
        choices=("true", "false"),
        default=None,
        help="override dedup.exact_enabled the same way.",
    )
    parser.add_argument(
        "--show-hashes",
        action="store_true",
        help="print each post's content hash, including ungrouped ones.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _load_config()
    settings = DedupSettings.from_config(config)

    if args.minhash_enabled is not None or args.exact_enabled is not None:
        settings = DedupSettings(
            exact_enabled=(
                settings.exact_enabled
                if args.exact_enabled is None
                else args.exact_enabled == "true"
            ),
            minhash_enabled=(
                settings.minhash_enabled
                if args.minhash_enabled is None
                else args.minhash_enabled == "true"
            ),
            shingle_k=settings.shingle_k,
            num_perm=settings.num_perm,
            jaccard_threshold=settings.jaccard_threshold,
            semantic_threshold=settings.semantic_threshold,
        )

    raw = DEMO if args.path is None else json.loads(Path(args.path).read_text(encoding="utf-8"))
    items = _to_items(raw)
    result = build_groups(items, settings)

    tier3 = (
        "off" if settings.semantic_threshold is None else f"cosine>={settings.semantic_threshold}"
    )
    print(
        f"exact={'on' if settings.exact_enabled else 'OFF (rollback state)'}  "
        f"minhash={'on' if settings.minhash_enabled else 'OFF (rollback state)'}  "
        f"jaccard>={settings.jaccard_threshold}  semantic={tier3}"
    )
    print(
        f"{len(items)} posts -> {len(result.groups)} group(s), "
        f"collapse rate {result.collapse_rate(len(items)):.0%}"
    )

    for group in result.groups:
        similarity = (
            "identical" if group.similarity is None else f"similarity {group.similarity:.3f}"
        )
        print(f"\n  {group.method} group, {group.member_count} members, {similarity}")
        for key in group.members:
            marker = (
                "representative -> enriched"
                if key == group.representative
                else (f"duplicate -> {result.rejections[key].reason}")
            )
            print(f"    #{key[1]:<4} {marker}")

    ungrouped = [i.key for i in items if i.key not in result.grouped_keys]
    if ungrouped:
        print(f"\n  ungrouped: {', '.join('#' + str(k[1]) for k in ungrouped)}")

    if args.show_hashes:
        print("\n  content hashes (P19 keys incremental enrichment on these):")
        for item in items:
            print(f"    #{item.row_id:<4} {content_hash(item.title, item.body)}")

    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main())
