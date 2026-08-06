import datetime
from rich.console import Console

from src.db.models import Lead, TrackedUser, ScrapeRun
from src.db.repositories.leads import LeadRepository
from src.subreddit_loader import get_all_subreddits

console = Console()


class UserScraper:
    def __init__(self, reddit_client, config):
        self.client = reddit_client
        self.config = config

    def run(self, session):
        total_leads = 0

        console.print("[bold cyan]Running user scraper...[/bold cyan]")

        tracked = session.query(TrackedUser).all()
        if not tracked:
            console.print("  [yellow]No tracked users yet. Users are added by the keyword/subreddit scrapers.[/yellow]")
            return 0

        subreddits = get_all_subreddits(self.config, session)
        repo = LeadRepository(session)

        for user in tracked:
            user_leads = 0
            posts = self.client.get_user_posts(user.username, limit=30)

            # One dedup query per user instead of one per post.
            for post in repo.filter_new(posts):
                sub_name = post["subreddit"]
                if sub_name.lower() not in subreddits:
                    continue

                created_utc = post["created_utc"] or datetime.datetime.utcnow()
                lead = Lead(
                    reddit_id=post["id"],
                    subreddit=sub_name,
                    author=post["author"],
                    title=post["title"],
                    body=(post["body"] or "")[:5000],
                    url=post["url"],
                    post_type="post",
                    score=post["score"],
                    num_comments=post["num_comments"],
                    intent_score=0,
                    matched_keywords="",
                    created_utc=created_utc,
                )
                session.add(lead)
                user_leads += 1

            user.last_seen = datetime.datetime.utcnow()
            user.post_count = user.post_count + len(posts)
            user.lead_count = user.lead_count + user_leads
            session.commit()

            total_leads += user_leads
            console.print(f"  [green]u/{user.username}:[/green] {user_leads} new posts tracked")

        run = ScrapeRun(
            scraper_type="user",
            posts_found=total_leads,
            leads_found=total_leads,
        )
        session.add(run)
        session.commit()

        console.print(f"[bold green]User scraper done: {total_leads} posts tracked[/bold green]")
        return total_leads

    @staticmethod
    def add_user(session, username):
        existing = session.query(TrackedUser).filter_by(username=username).first()
        if existing:
            return existing
        user = TrackedUser(username=username)
        session.add(user)
        session.commit()
        return user
