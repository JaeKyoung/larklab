"""Send paper digests to Slack."""

import time

from slack_sdk import WebClient

from larklab.config import Config
from larklab.load.slack_common import post, post_failed_papers, post_paper_card
from larklab.schemas import DailyDigest


def send_digest_to_slack(
    digests: list[DailyDigest],
    config: Config,
    num_emails: int = 0,
    num_parsed: int = 0,
) -> list[DailyDigest]:
    """Send paper digests to Slack, one message per batch.

    Returns list of successfully sent digests.
    """
    if not config.slack_bot_token:
        print("Slack bot token not configured, skipping Slack output.")
        return []

    client = WebClient(token=config.slack_bot_token)

    sent_digests = []
    for digest in digests:
        if _send_batch(client, config.slack_channel, digest):
            sent_digests.append(digest)

    total = sum(len(d.papers) for d in sent_digests)
    print(
        f"Sent {len(sent_digests)}/{len(digests)} batch(es) to "
        f"#{config.slack_channel} ({total} papers total)"
    )
    return sent_digests


def _send_batch(client: WebClient, channel: str, digest: DailyDigest) -> bool:
    """Send a single batch as summary + threaded papers."""
    count = len(digest.papers)
    summary = f"*Scholar Digest — {digest.date}*\n• {count} papers"

    thread_ts = post(client, channel, summary)
    if not thread_ts:
        return False

    failed_titles = []
    for i, paper in enumerate(digest.papers):
        if i > 0:
            time.sleep(1)
        text = paper.summary or paper.abstract or ""
        ok = post_paper_card(
            client,
            channel,
            thread_ts,
            title=paper.title,
            url=paper.url,
            journal=paper.journal,
            authors=paper.authors,
            text=text,
            similar_papers=paper.similar_papers,
        )
        if not ok:
            failed_titles.append(paper.title)
    if failed_titles:
        print(
            f"  Warning: {len(failed_titles)}/{len(digest.papers)} "
            "papers failed to post"
        )
        post_failed_papers(client, channel, thread_ts, failed_titles)
    return True
