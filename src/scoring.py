import re
import datetime
from src.subreddit_loader import get_scoring_settings, get_all_keywords


class LeadScorer:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session

        if session:
            settings = get_scoring_settings(config, session)
            high_intent, medium_intent = get_all_keywords(config, session)
        else:
            scoring = config.get("scoring", {})
            settings = {
                "keyword_weight": scoring.get("keyword_weight", 3),
                "upvote_weight": scoring.get("upvote_weight", 1),
                "comment_weight": scoring.get("comment_weight", 2),
                "recency_weight": scoring.get("recency_weight", 1.5),
                "high_intent_multiplier": scoring.get("high_intent_multiplier", 2),
            }
            high_intent = [kw.lower() for kw in config.get("keywords", {}).get("high_intent", [])]
            medium_intent = [kw.lower() for kw in config.get("keywords", {}).get("medium_intent", [])]

        self.keyword_weight = settings["keyword_weight"]
        self.upvote_weight = settings["upvote_weight"]
        self.comment_weight = settings["comment_weight"]
        self.recency_weight = settings["recency_weight"]
        self.high_intent_multiplier = settings["high_intent_multiplier"]
        self.high_intent = high_intent
        self.medium_intent = medium_intent

    def score_post(self, title, body="", upvotes=0, num_comments=0, created_utc=None):
        # Search results carry no score in the HTML, so upvotes may be None
        # meaning "unknown". Coerced to 0 for arithmetic only: the Lead row
        # still stores NULL, because "unknown" and "zero upvotes" are different
        # facts and conflating them would make the number a quiet lie.
        # Every existing value is unaffected -- 0 stays 0, N stays N.
        upvotes = upvotes or 0
        num_comments = num_comments or 0
        text = f"{title} {body}".lower()
        matched_keywords = []
        keyword_score = 0

        for kw in self.high_intent:
            if kw in text:
                matched_keywords.append(f"[HIGH]{kw}")
                keyword_score += self.keyword_weight * self.high_intent_multiplier

        for kw in self.medium_intent:
            if kw in text:
                matched_keywords.append(f"[MED]{kw}")
                keyword_score += self.keyword_weight

        upvote_score = min(upvotes, 100) * self.upvote_weight
        comment_score = min(num_comments, 50) * self.comment_weight

        recency_score = 0
        if created_utc:
            # Naive UTC on both sides: `created_utc` comes off reddit already
            # stripped to naive UTC, and subtracting an aware value would raise.
            now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            age_hours = (now - created_utc).total_seconds() / 3600
            recency_score = max(0, 100 - age_hours) * self.recency_weight / 100

        total = keyword_score + upvote_score + comment_score + recency_score

        return {
            "total": round(total, 2),
            "keyword_score": round(keyword_score, 2),
            "upvote_score": round(upvote_score, 2),
            "comment_score": round(comment_score, 2),
            "recency_score": round(recency_score, 2),
            "matched_keywords": matched_keywords,
        }

    def is_lead(self, score_result, min_score=5):
        return score_result["total"] >= min_score and len(score_result["matched_keywords"]) > 0
