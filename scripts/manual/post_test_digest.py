"""Send a one-email digest to Slack to check formatting end to end.

Manual check against live Gmail and Slack (posts to #journal-club):
    pixi run python scripts/manual/post_test_digest.py
"""

import logging

from larklab.config import load_config
from larklab.outputs.slack.digest import send_digest_to_slack
from larklab.processing.dedup import dedup_and_group_by_date
from larklab.sources.gmail.client import GmailClient

QUERY = "from:scholaralerts-noreply@google.com"
CHANNEL = "journal-club"


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load_config()
    gmail = GmailClient(config)

    message_ids = gmail.list_message_ids(QUERY, max_results=1, days_back=7)
    papers = gmail.parse_emails(gmail.fetch_full_messages(message_ids))
    digests = dedup_and_group_by_date(papers)

    print(f"Sending {sum(len(d.papers) for d in digests)} papers to Slack...")
    send_digest_to_slack(digests, token=config.slack_bot_token, channel=CHANNEL)


if __name__ == "__main__":
    main()
