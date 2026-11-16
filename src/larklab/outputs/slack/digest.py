"""Send Scholar digests to Slack."""

import logging

from slack_sdk import WebClient

from larklab.models import DailyDigest
from larklab.outputs.slack.paper_thread import PaperCard, post_paper_thread

logger = logging.getLogger(__name__)


def send_digest_to_slack(
    digests: list[DailyDigest], *, token: str, channel: str
) -> list[DailyDigest]:
    """Post one thread per digest. Returns the digests that were sent."""
    if not token:
        logger.warning("Slack bot token not configured, skipping Slack output.")
        return []

    client = WebClient(token=token)
    sent = [digest for digest in digests if _send_digest(client, channel, digest)]

    total_papers = sum(len(digest.papers) for digest in sent)
    logger.info(
        "Sent %d/%d batch(es) to #%s (%d papers total)",
        len(sent),
        len(digests),
        channel,
        total_papers,
    )
    return sent


def _send_digest(client: WebClient, channel: str, digest: DailyDigest) -> bool:
    headline = f"*Scholar Digest — {digest.date}*\n• {len(digest.papers)} papers"
    cards = [
        PaperCard(
            title=paper.title,
            url=paper.url,
            journal=paper.journal,
            authors=paper.authors,
            text=paper.summary or paper.abstract,
            similar_papers=paper.similar_papers,
        )
        for paper in digest.papers
    ]
    return post_paper_thread(client, channel, headline, cards).started
