"""Slack posting helpers shared by the digest and recommendation senders."""

import logging
import time
from dataclasses import dataclass, field

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackRequestError

from larklab.models import SimilarPapers

logger = logging.getLogger(__name__)

_ICON_URL = "https://raw.githubusercontent.com/JaeKyoung/larklab/main/img/icon.png"
_CARD_COLOR = "#CC7D5E"
_CARD_DELAY_SECONDS = 1  # avoids Slack's "high volume" warning
_MAX_ATTEMPTS = 3
_MAX_LISTED_FAILURES = 10


@dataclass(frozen=True)
class PaperCard:
    """Everything shown in one threaded paper attachment."""

    title: str
    url: str
    journal: str
    authors: list[str]
    text: str
    similar_papers: SimilarPapers | None = None


@dataclass(frozen=True)
class ThreadResult:
    started: bool  # the headline was posted
    posted: int  # cards that made it into the thread
    # positions in the `cards` list that were not posted; when the headline itself
    # failed that is every card
    failed_indexes: list[int] = field(default_factory=list)


def post_paper_thread(
    client: WebClient, channel: str, headline: str, cards: list[PaperCard]
) -> ThreadResult:
    """Post `headline`, then one threaded card per paper.

    A single failed card does not stop the rest; failures are listed in the thread
    and reported back so the caller can try them again later.
    """
    thread_ts = post_message(client, channel, headline)
    if not thread_ts:
        return ThreadResult(
            started=False, posted=0, failed_indexes=list(range(len(cards)))
        )

    failed_indexes = []
    for index, card in enumerate(cards):
        if index > 0:
            time.sleep(_CARD_DELAY_SECONDS)
        if not _post_card(client, channel, thread_ts, card):
            failed_indexes.append(index)

    if failed_indexes:
        logger.warning(
            "  Warning: %d/%d papers failed to post", len(failed_indexes), len(cards)
        )
        _post_failure_notice(
            client, channel, thread_ts, [cards[i].title for i in failed_indexes]
        )
    return ThreadResult(
        started=True,
        posted=len(cards) - len(failed_indexes),
        failed_indexes=failed_indexes,
    )


def post_message(
    client: WebClient,
    channel: str,
    text: str,
    thread_ts: str | None = None,
    attachments: list | None = None,
) -> str | None:
    """Post a message, waiting out rate limits. Returns its timestamp or None."""
    for _ in range(_MAX_ATTEMPTS):
        try:
            response = client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
                attachments=attachments,
                unfurl_links=False,
                unfurl_media=False,
            )
            return response["ts"]
        except SlackApiError as error:
            if error.response["error"] != "ratelimited":
                logger.error("Slack error: %s", error.response["error"])
                return None
            wait_seconds = int(error.response.headers.get("Retry-After", 1))
            logger.warning("  Rate limited, waiting %ds...", wait_seconds)
            time.sleep(wait_seconds)
        except (SlackRequestError, OSError) as error:  # network down, timeout, ...
            logger.error("Slack request failed: %s", error)
            return None
    logger.error("Slack error: rate limit retries exhausted")
    return None


def _post_card(
    client: WebClient, channel: str, thread_ts: str, card: PaperCard
) -> bool:
    fields = [
        {
            "title": "Authors",
            "value": ", ".join(card.authors) or "Unknown",
            "short": False,
        }
    ]
    for rank, (reference_title, score) in enumerate(card.similar_papers or [], 1):
        fields.append(
            {
                "title": f"Top {rank} related paper (similarity: {score:.3f})",
                "value": reference_title,
                "short": False,
            }
        )

    attachment = {
        "color": _CARD_COLOR,
        "fallback": card.title,
        "author_name": card.journal or "Unknown",
        "author_icon": _ICON_URL,
        "title": card.title,
        "title_link": card.url,
        "text": card.text,
        "fields": fields,
        "mrkdwn_in": ["text"],
    }
    posted = post_message(
        client, channel, "", thread_ts=thread_ts, attachments=[attachment]
    )
    return posted is not None


def _post_failure_notice(
    client: WebClient, channel: str, thread_ts: str, titles: list[str]
) -> None:
    listed = titles[:_MAX_LISTED_FAILURES]
    lines = "\n".join(f"• {title}" for title in listed)
    hidden = len(titles) - len(listed)
    if hidden > 0:
        lines += f"\n• …and {hidden} more"
    post_message(
        client,
        channel,
        f":warning: {len(titles)} paper card(s) failed to post:\n{lines}",
        thread_ts=thread_ts,
    )
