import datetime
from rich.console import Console

from src.db.models import Lead, Subreddit, ScrapeRun
from src.db.repositories.leads import LeadRepository
from src.scoring import LeadScorer
from src.subreddit_loader import get_all_subreddits

console = Console()


class SubredditScraper:
    def __init__(self, reddit_client, config):
        self.client = reddit_client
        self.config = config

    def run(self, session):
        total_leads = 0
        total_posts = 0
        subreddits = get_all_subreddits(self.config, session)
        scorer = LeadScorer(self.config, session)
        repo = LeadRepository(session)

        console.print(f"[bold cyan]Running subreddit scraper across {len(subreddits)} subreddits...[/bold cyan]")

        for sub_name in subreddits:
            sub_leads = 0
            posts = self.client.get_new_posts(sub_name, limit=100)
            total_posts += len(posts)

            self._update_subreddit_info(session, sub_name)

            # One dedup query for the whole page. This also drops posts repeated
            # within the page, which the old per-post check let through and the
            # reddit_id unique index then rejected at commit time.
            for post in repo.filter_new(posts):
                created_utc = post["created_utc"] or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                score_result = scorer.score_post(
                    title=post["title"],
                    body=post["body"] or "",
                    upvotes=post["score"],
                    num_comments=post["num_comments"],
                    created_utc=created_utc,
                )

                if scorer.is_lead(score_result, min_score=3):
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
                        intent_score=score_result["total"],
                        matched_keywords=", ".join(score_result["matched_keywords"]),
                        created_utc=created_utc,
                    )
                    session.add(lead)
                    sub_leads += 1

            session.commit()
            total_leads += sub_leads
            console.print(f"  [green]r/{sub_name}:[/green] {len(posts)} posts scanned, {sub_leads} leads")

        run = ScrapeRun(
            scraper_type="subreddit",
            posts_found=total_posts,
            leads_found=total_leads,
        )
        session.add(run)
        session.commit()

        console.print(f"[bold green]Subreddit scraper done: {total_posts} posts scanned, {total_leads} leads[/bold green]")
        return total_leads

    def _update_subreddit_info(self, session, sub_name):
        info = self.client.get_subreddit_info(sub_name)
        if not info:
            return

        sub = session.query(Subreddit).filter_by(name=sub_name).first()
        if sub:
            sub.description = info["description"]
            sub.subscriber_count = info["subscribers"]
            sub.last_scraped = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        else:
            sub = Subreddit(
                name=sub_name,
                description=info["description"],
                subscriber_count=info["subscribers"],
                last_scraped=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            )
            session.add(sub)
