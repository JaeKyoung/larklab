"""Send paper recommendations to Slack."""

import time
from collections import defaultdict
from datetime import date

from slack_sdk import WebClient

from larklab.config import Config
from larklab.load.slack_common import post, post_failed_papers, post_paper_card
from larklab.schemas import Paper

ScoredPaper = tuple[Paper, float, list[tuple[str, float]]]


def send_recommendations_to_slack(
    by_date: dict[date | None, list[ScoredPaper]],
    config: Config,
    date_totals: dict[date | None, dict[str, int]],
) -> bool:
    """Send paper recommendations to Slack, one thread per date."""
    if not config.slack_bot_token:
        print("Slack bot token not configured, skipping Slack output.")
        return False

    client = WebClient(token=config.slack_bot_token)
    total_sent = 0

    for pub_date in sorted(by_date, key=lambda d: d or date.min, reverse=True):
        papers = by_date[pub_date]
        label = pub_date.strftime("%Y-%m-%d") if pub_date else "unknown"

        totals = date_totals.get(pub_date, {})
        filtered_counts: dict[str, int] = defaultdict(int)
        for p, _, _ in papers:
            filtered_counts[p.journal.lower()] += 1
        lines = [f"*Paper Recommendations — {label}*"]
        for src in totals:
            lines.append(f"• {src}: {filtered_counts[src]}/{totals[src]}")
        summary = "\n".join(lines)

        thread_ts = post(client, config.slack_channel, summary)
        if not thread_ts:
            continue

        failed = []
        for i, (paper, score, similar) in enumerate(papers):
            if i > 0:
                time.sleep(1)
            ok = post_paper_card(
                client,
                config.slack_channel,
                thread_ts,
                title=paper.title,
                url=paper.url,
                journal=paper.journal,
                authors=paper.authors,
                text=paper.abstract,
                similar_papers=similar,
            )
            if not ok:
                failed.append(paper.title)

        if failed:
            print(f"  Warning: {len(failed)}/{len(papers)} papers failed to post")
            post_failed_papers(client, config.slack_channel, thread_ts, failed)

        total_sent += len(papers) - len(failed)

    print(f"Sent {total_sent} recommendations to #{config.slack_channel}")
    return True
