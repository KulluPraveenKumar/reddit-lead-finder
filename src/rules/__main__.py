"""``python -m src.rules "<title>"`` -- ask the rule engine about one post.

**This exists because P9 has nothing else a person can look at.** The phase adds
no page, no endpoint, no log line and no database row, and
[35 §1](../../docs/35-testing-strategy.md) requires that the manual guide be
executable by a non-developer: *"If a step cannot be verified without reading
code, the step is wrong."* Without this module the guide would be a list of
pytest invocations, which is exactly the kind of step that rule forbids.

It is outside [34 §P9](../../docs/34-implementation-plan.md)'s Files row, which
[34 §1.1](../../docs/34-implementation-plan.md) declares *"a guide, not a
contract"*. P5 took the same latitude for its ``feed`` CLI and P6 for
``triage.py``, whose docstring records the precedent explicitly.

⚠️ **It imports nothing from ``src.ai``**, and fence 2 covers it automatically
because it lives under ``src/rules/``. A convenience script is exactly where a
boundary quietly leaks.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from . import RulesSettings, evaluate


def _load_config() -> dict[str, Any]:
    """The real ``config.yaml``, or empty defaults if it cannot be read.

    A demo that refused to run because the config was missing would be a worse
    diagnostic than one that says which settings it used.
    """
    try:
        from src.config import load_config

        return load_config() or {}
    except Exception as exc:  # pragma: no cover - exercised by hand, not in CI
        print(f"note: could not read config.yaml ({exc}); using defaults", file=sys.stderr)
        return {}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.rules",
        description="Judge one Reddit post title with the deterministic rule engine.",
    )
    parser.add_argument("title", help="the post title to judge")
    parser.add_argument("--author", default=None, help="the post author, if you want it checked")
    parser.add_argument("--body", default=None, help="the post body, to exercise the length rule")
    parser.add_argument(
        "--rules-enabled",
        choices=("true", "false"),
        default=None,
        help=(
            "override pipeline.rules_enabled without editing config.yaml. "
            "This is how the manual guide demonstrates the rollback: editing the "
            "file by hand risks a Notepad-added BOM, after which every command in "
            "the project fails with 'Missing required config key: subreddits' -- "
            "which reads as a defect in this phase and is not one."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _load_config()

    settings = RulesSettings.from_config(config)
    if args.rules_enabled is not None:
        settings = RulesSettings(
            enabled=args.rules_enabled == "true",
            min_chars=settings.min_chars,
            skip_deleted_authors=settings.skip_deleted_authors,
            skip_bot_authors=settings.skip_bot_authors,
        )

    negative_terms = ((config.get("discovery") or {}).get("negative_terms")) or []

    result = evaluate(
        title=args.title,
        author=args.author,
        text=args.body,
        settings=settings,
        negative_terms=negative_terms,
    )

    state = "on" if settings.enabled else "OFF (rollback state)"
    print(f"rules: {state}   min_chars={settings.min_chars}")
    if result.rejected:
        print(f"reject · {result.reason} · {result.detail}")
    else:
        print("admit")
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main())
