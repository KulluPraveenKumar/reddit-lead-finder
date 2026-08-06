import sys
import time

import schedule
from rich.console import Console
from rich.panel import Panel

from src.config import load_config
from src.dashboard.app import create_app
from src.db.database import get_session, init_db
from src.reddit_client import RedditClient
from src.scrapers.keyword_scraper import KeywordScraper
from src.scrapers.subreddit_scraper import SubredditScraper
from src.scrapers.user_scraper import UserScraper

console = Console()


def _startup_banner(config):
    """Migration state and AI status, printed once.

    AI problems are reported as *status*, never as failures: scraping and the
    legacy dashboard work with no key, no APP_SECRET_KEY, and no network.
    """
    from src.db.database import DB_PATH
    from src.db.migrate import MigrationRunner

    try:
        status = MigrationRunner(DB_PATH).status()
        state = "up to date" if status.is_current else f"{status.current} -> {status.head}"
        console.print(f"[dim]Migrations[/dim]      {state} ({status.current})")
    except Exception as exc:
        console.print(f"[dim]Migrations[/dim]      [yellow]unknown ({exc})[/yellow]")

    try:
        from src.ai.service import AIService
        from src.settings import get_settings

        service = AIService(get_settings(config))
        key = service.credentials.status()
        colour = {
            "valid": "green",
            "insufficient_balance": "yellow",
            "unreachable": "yellow",
            "undecryptable": "yellow",
            "invalid_key": "red",
        }.get(key.status, "dim")
        detail = f" · {key.model_id}" if key.model_id else ""
        console.print(
            f"[dim]AI provider[/dim]     {service.provider_name}{detail} · "
            f"[{colour}]{key.status}[/{colour}]"
        )
        if key.status != "valid":
            console.print("[dim]                AI features disabled. Scraping is unaffected.[/dim]")
    except Exception as exc:
        console.print(f"[dim]AI provider[/dim]     [dim]unavailable ({exc})[/dim]")


def cmd_scrape(config, scraper_type=None):
    init_db()
    client = RedditClient(config)
    session = get_session()

    try:
        if scraper_type is None or scraper_type == "keyword":
            KeywordScraper(client, config).run(session)
        if scraper_type is None or scraper_type == "subreddit":
            SubredditScraper(client, config).run(session)
        if scraper_type is None or scraper_type == "user":
            UserScraper(client, config).run(session)
    finally:
        session.close()


def cmd_dashboard(config):
    dash_config = config.get("dashboard", {})
    host = dash_config.get("host", "127.0.0.1")
    port = dash_config.get("port", 5000)

    console.print(Panel(f"[bold green]Dashboard running at http://{host}:{port}[/bold green]"))
    _startup_banner(config)
    app = create_app()
    app.run(host=host, port=port, debug=False)


def cmd_schedule(config):
    interval = config.get("schedule", {}).get("interval_minutes", 60)
    console.print(Panel(f"[bold cyan]Scheduling scrapers every {interval} minutes. Press Ctrl+C to stop.[/bold cyan]"))

    def job():
        console.print("\n[bold]--- Scheduled scrape starting ---[/bold]")
        try:
            cmd_scrape(config)
        except Exception as e:
            console.print(f"[red]Scrape error: {e}[/red]")

    job()
    schedule.every(interval).minutes.do(job)

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler stopped.[/yellow]")


def cmd_add_user(config, username):
    init_db()
    session = get_session()
    try:
        user = UserScraper.add_user(session, username)
        console.print(f"[green]Now tracking user: u/{user.username}[/green]")
    finally:
        session.close()


def cmd_migrate(config, args):
    """Wraps Alembic so the operator never needs to know Alembic exists."""
    from src.db.database import DB_PATH
    from src.db.migrate import MigrationRunner

    runner = MigrationRunner(DB_PATH)
    action = args[1] if len(args) > 1 else "upgrade"

    if action == "status":
        status = runner.status()
        console.print(f"Current: [bold]{status.current or '(none)'}[/bold]")
        console.print(f"Head:    [bold]{status.head}[/bold]")
        console.print(
            "[green]Up to date.[/green]" if status.is_current else "[yellow]Upgrade available.[/yellow]"
        )
        return

    if action == "stamp":
        if len(args) < 3:
            console.print("[red]Usage: python main.py migrate stamp REVISION[/red]")
            return
        runner.stamp(args[2])
        console.print(f"[green]Stamped {args[2]}[/green]")
        return

    if action == "downgrade":
        if len(args) < 3:
            console.print("[red]Usage: python main.py migrate downgrade REVISION[/red]")
            return
        backup = runner.backup()
        console.print(f"[dim]Backup: {backup}[/dim]")
        runner.downgrade(args[2])
        console.print(f"[green]Downgraded to {args[2]}[/green]")
        return

    status = runner.ensure_current()
    if status.backup_path:
        console.print(f"[dim]Backup: {status.backup_path}[/dim]")
    console.print(f"[green]Schema at {status.current}[/green]")


def cmd_ai(config, args):
    from src.ai.service import AIService
    from src.settings import get_settings

    service = AIService(get_settings(config))
    action = args[1] if len(args) > 1 else "status"

    if action == "status":
        key = service.credentials.status()
        console.print(f"Provider:       [bold]{service.provider_name}[/bold]")
        console.print(f"Status:         [bold]{key.status}[/bold]")
        console.print(f"Key:            {key.fingerprint or '(none stored)'}")
        console.print(f"Model:          {key.model_id or '(unknown)'}")
        console.print(f"Last validated: {key.last_validated_at or 'never'}")
        if key.last_error:
            console.print(f"[yellow]{key.last_error}[/yellow]")
        return

    if action == "test":
        console.print("[dim]Testing connection...[/dim]")
        result = service.test_connection()
        if result.ok:
            console.print(
                f"[green]Connected in {result.latency_ms} ms · {result.model}[/green]"
            )
        else:
            console.print(f"[red]{result.error}[/red]  (status: {result.status})")
        return

    if action == "usage":
        summary = service.usage_summary()
        console.print(f"Run cost:  ${summary['run_cost_usd']:.6f}")
        console.print(f"Day cost:  ${summary['day_cost_usd']:.6f}")
        console.print(f"Calls:     {summary['metrics']['calls']}")
        console.print(f"Cache hit: {summary['metrics']['prefix_cache_ratio']:.1%}")
        return

    console.print(f"[red]Unknown ai subcommand: {action}[/red]")


def print_help():
    help_text = r"""[bold]Reddit Lead Finder[/bold] (Web Scraper)

[bold cyan]Usage:[/bold cyan]
  python main.py scrape \[--scraper TYPE]   Run scrapers (keyword|subreddit|user|all)
  python main.py dashboard                 Start web dashboard
  python main.py schedule                  Run scrapers on a schedule
  python main.py add-user USERNAME         Track a Reddit user
  python main.py migrate \[status|upgrade|stamp REV|downgrade REV]
  python main.py ai \[status|test|usage]    AI provider status and connectivity

[bold cyan]Examples:[/bold cyan]
  python main.py scrape                    Run all scrapers
  python main.py scrape --scraper keyword  Run keyword scraper only
  python main.py schedule                  Auto-scrape every 60 min
  python main.py add-user some_redditor    Track a specific user
  python main.py migrate status            Show schema version
  python main.py ai test                   Verify the API key works
"""
    console.print(help_text)


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print_help()
        return

    from src.obs.logging import configure_logging
    from src.settings import load_env

    load_env()

    config = load_config()
    log_config = config.get("logging", {})
    configure_logging(
        level=log_config.get("level", "INFO"),
        fmt=log_config.get("format", "console"),
    )

    command = args[0]

    if command == "scrape":
        scraper_type = None
        if "--scraper" in args:
            idx = args.index("--scraper")
            if idx + 1 < len(args):
                scraper_type = args[idx + 1]
        cmd_scrape(config, scraper_type)

    elif command == "dashboard":
        cmd_dashboard(config)

    elif command == "schedule":
        cmd_schedule(config)

    elif command == "add-user":
        if len(args) < 2:
            console.print("[red]Usage: python main.py add-user USERNAME[/red]")
            return
        cmd_add_user(config, args[1])

    elif command == "migrate":
        cmd_migrate(config, args)

    elif command == "ai":
        cmd_ai(config, args)

    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        print_help()


if __name__ == "__main__":
    main()
