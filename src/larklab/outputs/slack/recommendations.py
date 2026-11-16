"""Send paper recommendations to Slack."""

import logging

from slack_sdk import WebClient

from larklab.models import Recommendation, RecommendationResult
from larklab.outputs.slack.paper_thread import PaperCard, post_paper_thread

logger = logging.getLogger(__name__)


def send_recommendations_to_slack(
    result: RecommendationResult, *, token: str, channel: str
) -> list[Recommendation]:
    """Post one thread per publication date.

    Returns the recommendations that could not be posted — all of them when Slack
    is not configured — so the caller can keep them and send them next time.
    """
    if not token:
        logger.warning("Slack bot token not configured, skipping Slack output.")
        return list(result.recommendations)

    client = WebClient(token=token)
    undelivered: list[Recommendation] = []
    total_sent = 0
    for published, recommendations in result.by_date().items():
        label = published.isoformat() if published else "unknown"
        headline_lines = [f"*Paper Recommendations — {label}*"] + [
            f"• {source}: {kept}/{total}"
            for source, kept, total in result.source_counts(published)
        ]
        cards = [
            PaperCard(
                title=rec.paper.title,
                url=rec.paper.url,
                journal=rec.paper.journal,
                authors=rec.paper.authors,
                text=rec.paper.abstract,
                similar_papers=rec.similar_papers,
            )
            for rec in recommendations
        ]
        thread = post_paper_thread(client, channel, "\n".join(headline_lines), cards)
        total_sent += thread.posted
        undelivered.extend(recommendations[i] for i in thread.failed_indexes)

    logger.info("Sent %d recommendations to #%s", total_sent, channel)
    return undelivered
