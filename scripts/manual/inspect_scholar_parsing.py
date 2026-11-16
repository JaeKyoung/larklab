"""Fetch a few Scholar emails and inspect parsing results in detail.

Manual check against the live Gmail account (read-only):
    pixi run python scripts/manual/inspect_scholar_parsing.py
"""

from larklab.config import load_config
from larklab.sources.gmail.client import GmailClient

QUERY = "from:scholaralerts-noreply@google.com"
MAX_EMAILS = 3
DAYS_BACK = 7


def main():
    gmail = GmailClient(load_config())
    message_ids = gmail.list_message_ids(QUERY, MAX_EMAILS, DAYS_BACK)
    raw_emails = gmail.fetch_full_messages(message_ids)

    for number, email in enumerate(raw_emails, 1):
        print(f"\n{'=' * 70}")
        print(f"EMAIL {number} (id: {email['id']})")
        print(f"{'=' * 70}")

        headers = email.get("payload", {}).get("headers", [])
        subject = next(
            (h["value"] for h in headers if h["name"].lower() == "subject"),
            "N/A",
        )
        print(f"Subject: {subject}\n")

        papers = gmail.parse_emails([email])
        print(f"--- Parsed {len(papers)} papers ---\n")
        for index, paper in enumerate(papers, 1):
            ellipsis = "..." if len(paper.abstract) > 150 else ""
            print(f"  [{index}]")
            print(f"  Title:    {paper.title}")
            print(f"  Authors:  {paper.authors}")
            print(f"  Journal:  {paper.journal}")
            print(f"  Abstract: {paper.abstract[:150]}{ellipsis}")
            print(f"  URL:      {paper.url}")
            print(f"  Date:     {paper.received_at}")
            print()


if __name__ == "__main__":
    main()
