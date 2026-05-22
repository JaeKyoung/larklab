"""Shared Slack posting utilities."""

import time

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

_ICON_URL = "https://raw.githubusercontent.com/JaeKyoung/larklab/main/img/icon.png"


def post_paper_card(
    client: WebClient,
    channel: str,
    thread_ts: str,
    *,
    title: str,
    url: str,
    journal: str,
    authors: list[str],
    text: str,
    similar_papers: list[tuple[str, float]] | None = None,
) -> bool:
    """Post a paper card as a threaded Slack attachment."""
    author_str = ", ".join(authors) if authors else "Unknown"

    fields = [{"title": "Authors", "value": author_str, "short": False}]
    if similar_papers:
        for rank, (ref_title, score) in enumerate(similar_papers, 1):
            fields.append(
                {
                    "title": f"Top {rank} related paper (similarity: {score:.3f})",
                    "value": ref_title,
                    "short": False,
                }
            )

    attachment = {
        "color": "#CC7D5E",
        "fallback": title,
        "author_name": journal or "Unknown",
        "author_icon": _ICON_URL,
        "title": title,
        "title_link": url,
        "text": text,
        "fields": fields,
        "mrkdwn_in": ["text"],
    }
    return (
        post(client, channel, "", thread_ts=thread_ts, attachments=[attachment])
        is not None
    )


def post_failed_papers(
    client: WebClient, channel: str, thread_ts: str, titles: list[str]
) -> None:
    """Post a thread warning for paper cards that failed to send."""
    shown = titles[:10]
    lines = "\n".join(f"• {title}" for title in shown)
    extra = len(titles) - len(shown)
    if extra > 0:
        lines += f"\n• …and {extra} more"
    post(
        client,
        channel,
        f":warning: {len(titles)} paper card(s) failed to post:\n{lines}",
        thread_ts=thread_ts,
    )


def post(
    client: WebClient,
    channel: str,
    text: str,
    thread_ts: str | None = None,
    attachments: list | None = None,
) -> str | None:
    """Post a message to Slack with retry on rate limit."""
    for attempt in range(3):
        try:
            result = client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
                attachments=attachments,
                unfurl_links=False,
                unfurl_media=False,
            )
            return result["ts"]
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 1))
                print(f"  Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after)
            else:
                print(f"Slack error: {e.response['error']}")
                return None
    print("Slack error: rate limit retries exhausted")
    return None
