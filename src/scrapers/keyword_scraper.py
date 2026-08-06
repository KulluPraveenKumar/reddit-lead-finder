import datetime
from rich.console import Console

from src.db.models import Lead, ScrapeRun
from src.db.repositories.leads import LeadRepository
from src.scoring import LeadScorer
from src.subreddit_loader import get_all_subreddits, get_all_keywords, get_all_search_queries

console = Console()


class KeywordScraper:
    def __init__(self, reddit_client, config):
        self.client = reddit_client
        self.config = config

    def run(self, session):
        total_leads = 0
        subreddits = get_all_subreddits(self.config, session)
        high_intent, medium_intent = get_all_keywords(self.config, session)
        all_queries = high_intent + medium_intent
        custom_queries = get_all_search_queries(session)
        all_searches = all_queries + custom_queries

        scorer = LeadScorer(self.config, session)
        repo = LeadRepository(session)
        console.print(f"[bold cyan]Running keyword scraper across {len(subreddits)} subreddits with {len(all_searches)} queries...[/bold cyan]")

        for sub_name in subreddits:
            sub_leads = 0
            seen_ids = set()

            for query in all_searches:
                posts = self.client.search_posts(query, subreddit=sub_name, limit=50)

                # seen_ids spans the queries for this subreddit; filter_new does
                # the database check for the whole result set in one query.
                posts = [p for p in posts if p["id"] not in seen_ids]
                seen_ids.update(p["id"] for p in posts)

                for post in repo.filter_new(posts):
                    created_utc = post["created_utc"] or datetime.datetime.utcnow()
                    score_result = scorer.score_post(
                        title=post["title"],
                        body=post["body"] or "",
                        upvotes=post["score"],
                        num_comments=post["num_comments"],
                        created_utc=created_utc,
                    )

                    if scorer.is_lead(score_result):
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
            console.print(f"  [green]r/{sub_name}:[/green] {sub_leads} leads found")

        run = ScrapeRun(
            scraper_type="keyword",
            posts_found=total_leads,
            leads_found=total_leads,
        )
        session.add(run)
        session.commit()

        console.print(f"[bold green]Keyword scraper done: {total_leads} total leads[/bold green]")
        return total_leads
