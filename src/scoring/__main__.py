"""``python -m src.scoring`` — pre-score posts and show every component.

[35 §1](../../docs/35-testing-strategy.md) requires the manual guide to be
executable by a non-developer — *"if a step cannot be verified without reading
code, the step is wrong"*. P11 does put a funnel on the run page, but reaching it
needs a full orchestrated run against live Reddit; this module lets a tester see
the **arithmetic** on known input in one command, so a wrong number can be
attributed to the score rather than to the network.

Outside the Files row, which [34 §1.1](../../docs/34-implementation-plan.md)
calls *"a guide, not a contract"*. P5's ``feed`` CLI, P6's ``triage.py``, P9's
``python -m src.rules`` and P10's ``python -m src.dedupe`` are the precedents,
and this is the fifth.

⚠ **Imports nothing from ``src.ai``**, and fence 2 covers it automatically
because it lives under ``src/scoring/``. A convenience script is exactly where a
boundary quietly leaks.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

from . import ABSENT_COMPONENTS, WEIGHTS, PrescoreSettings, normalised_weights
from .prescore import ScoredItem, prescore

#: A worked corpus, used when no file and no title is given. Four posts chosen so
#: one run shows the score doing all four of its jobs: a strong lead, a weak one
#: that falls under the floor, one rejected by a hard filter before the floor is
#: reached, and one whose age puts it outside the window.
DEMO: list[dict[str, Any]] = [
    {
        "title": "Looking for a CRM — any recommendations for a small team?",
        "body": (
            "We are five people and our spreadsheets are falling apart. I have been "
            "struggling with keeping track of who spoke to which customer, and I need "
            "help with picking something that will not cost a fortune. Any "
            "recommendations from people who have actually migrated off a spreadsheet? "
            "What tool do you use day to day, and would you pick it again?"
        ),
        "score": 42,
        "num_comments": 17,
        "age_days": 1,
    },
    {
        "title": "Shipped a small update today",
        "body": (
            "Nothing dramatic to report, just a quiet week of cleaning up some of the "
            "rough edges that had been bothering me for a while now. Onwards."
        ),
        "score": 2,
        "num_comments": 0,
        "age_days": 4,
    },
    {
        "title": "[HIRING] Senior backend engineer, remote",
        "body": "We are hiring for a remote senior backend role. Competitive salary.",
        "score": 30,
        "num_comments": 9,
        "age_days": 2,
    },
    {
        "title": "Looking for a CRM — any recommendations for a small team?",
        "body": (
            "Identical to the first post in every respect except its age, which is "
            "what puts it outside the run window and rejects it before the floor."
        ),
        "score": 42,
        "num_comments": 17,
        "age_days": 400,
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.scoring",
        description=(
            "Pre-score posts and show every component. Deterministic, offline, "
            "and it makes no AI call -- P11 makes none at all."
        ),
    )
    parser.add_argument("title", nargs="?", help="score a single post given as a title")
    parser.add_argument("--body", default="", help="the post body, with --title")
    parser.add_argument("--author", default="a_real_person")
    parser.add_argument("--score", type=int, default=None, help="upvotes; omit for unknown")
    parser.add_argument(
        "--num-comments", type=int, default=None, help="comment count; omit for unknown"
    )
    parser.add_argument("--age-days", type=float, default=1.0)
    parser.add_argument("--file", type=Path, help="a JSON list of posts instead")
    parser.add_argument(
        "--prescore-enabled",
        choices=("true", "false"),
        default="true",
        help="P11's rollback. `false` scores nothing and admits everything.",
    )
    parser.add_argument(
        "--admission-floor",
        type=float,
        default=None,
        help="override pipeline.prescore_admission_floor (default 35)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    config = _config(args)
    settings = PrescoreSettings.from_config(config)
    tiers = {k: list(v) for k, v in (config.get("keywords") or {}).items()}

    posts = _posts(args)
    now = datetime.datetime(2026, 8, 15, 12, 0, 0)

    results = []
    for post in posts:
        age = float(post.get("age_days", 1.0))
        item = ScoredItem(
            title=post.get("title") or "",
            body=post.get("body") or "",
            author=post.get("author") or args.author,
            score=post.get("score"),
            num_comments=post.get("num_comments"),
            created_utc=now - datetime.timedelta(days=age),
        )
        results.append((item, prescore(item, settings, keyword_tiers=tiers, now=now)))

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "title": item.title,
                        "total": result.total,
                        "decision": result.decision,
                        "reason": result.reason,
                        "detail": result.detail,
                        "components": result.components,
                        "absent": result.absent,
                    }
                    for item, result in results
                ],
                indent=2,
            )
        )
        return 0

    _report(results, settings)
    return 0


def _config(args: argparse.Namespace) -> dict[str, Any]:
    """The real ``config.yaml`` where it can be read, with the flags applied on top.

    Falls back to the shipped defaults rather than failing: the point of this
    command is to demonstrate the arithmetic, and a tester running it from a
    directory without a config should still see a score.
    """
    config: dict[str, Any] = {}
    try:
        from src.config import load_config

        config = load_config() or {}
    except Exception:  # noqa: BLE001 - the demo must run without a config file
        config = {}

    if not config.get("keywords"):
        config["keywords"] = {
            "high_intent": ["looking for", "any recommendations", "what tool do you use"],
            "medium_intent": ["how do i", "struggling with", "need help with"],
        }

    pipeline = dict(config.get("pipeline") or {})
    pipeline["prescore_enabled"] = args.prescore_enabled == "true"
    if args.admission_floor is not None:
        pipeline["prescore_admission_floor"] = args.admission_floor
    config["pipeline"] = pipeline
    return config


def _posts(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.file:
        return json.loads(args.file.read_text(encoding="utf-8"))
    if args.title:
        return [
            {
                "title": args.title,
                "body": args.body,
                "author": args.author,
                "score": args.score,
                "num_comments": args.num_comments,
                "age_days": args.age_days,
            }
        ]
    return DEMO


def _report(results: list[tuple[ScoredItem, Any]], settings: PrescoreSettings) -> None:
    weights = normalised_weights(settings.weights)

    print(f"Admission floor: {settings.admission_floor:g}   (pipeline.prescore_admission_floor)")
    print(f"Weights, normalised from docs/04 section 9.1 (raw: {WEIGHTS}):")
    for name, weight in sorted(weights.items(), key=lambda kv: -kv[1]):
        print(f"    {name:<18} {weight:.4f}")
    print("\nNot shipped in P11 -- declared absent, never scored as 0.0:")
    for name, owner in ABSENT_COMPONENTS.items():
        print(f"    {name:<18} {owner}")

    for item, result in results:
        title = item.title if len(item.title) <= 66 else item.title[:63] + "..."
        print(f"\n{'-' * 78}\n{title}")
        if result.components:
            for name, value in result.components.items():
                contribution = 100.0 * weights.get(name, 0.0) * value
                print(
                    f"    {name:<18} {value:>6.3f}  x {weights.get(name, 0.0):.4f}"
                    f"  = {contribution:>6.2f}"
                )
        print(f"    {'TOTAL':<18} {result.total:>6.2f} / 100")
        verdict = result.decision.upper()
        if result.reason:
            verdict += f"  ({result.reason}"
            verdict += f": {result.detail})" if result.detail else ")"
        elif result.detail:
            verdict += f"  ({result.detail})"
        print(f"    {'VERDICT':<18} {verdict}")

    print(f"\n{'-' * 78}")
    print("AI calls made: 0. P11 makes none -- src/scoring/ cannot import src.ai (R3).")


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
