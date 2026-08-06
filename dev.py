#!/usr/bin/env python
"""Convenience launcher: ``python dev.py`` == ``python main.py dashboard``.

Exists because "dev" is the verb people reach for, and because this project is
Python where the muscle memory is often Node. It adds no dependency and no build
step; it is three lines of delegation and a preflight check that turns the
common setup mistakes into sentences instead of tracebacks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _fail(message: str) -> None:
    print(f"\n  {message}\n", file=sys.stderr)
    sys.exit(1)


def preflight() -> None:
    # ruff flags this as dead code because pyproject declares requires-python
    # >=3.11 -- but that is only enforced by pip, and this script is run
    # directly. On an older interpreter the check is the difference between a
    # clear sentence and a SyntaxError from deep inside an import.
    if sys.version_info < (3, 11):  # noqa: UP036
        _fail(
            f"Python 3.11+ is required; this is {sys.version_info.major}.{sys.version_info.minor}."
        )

    missing = []
    for module, package in (
        ("flask", "Flask"),
        ("sqlalchemy", "SQLAlchemy"),
        ("alembic", "alembic"),
        ("pydantic", "pydantic"),
        ("cryptography", "cryptography"),
        ("dotenv", "python-dotenv"),
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
        ("yaml", "PyYAML"),
        ("rich", "rich"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        _fail(
            "Missing dependencies: "
            + ", ".join(missing)
            + "\n  Install them with:  python -m pip install -r requirements.txt"
        )

    if not (ROOT / "config.yaml").exists():
        _fail("config.yaml is missing. It is required and should be in the repository.")

    if not (ROOT / ".env").exists():
        # A warning, not an error: everything except AI works without it.
        print(
            "\n  Note: no .env file. AI features will be disabled.\n"
            "  To enable them:\n"
            "    cp .env.example .env\n"
            '    python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
            "  and paste the result as APP_SECRET_KEY.\n",
            file=sys.stderr,
        )


def main() -> None:
    preflight()
    raise SystemExit(
        subprocess.call([sys.executable, str(ROOT / "main.py"), "dashboard", *sys.argv[1:]])
    )


if __name__ == "__main__":
    main()
