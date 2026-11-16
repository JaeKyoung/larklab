"""Parse Google Scholar alert emails.

Fragile by nature: it depends on Google's HTML layout. All of that knowledge
lives here, reached only through `GmailClient.parse_emails`.
"""

import base64
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from larklab.models import ScholarPaper


def parse_scholar_email(raw_message: dict) -> list[ScholarPaper]:
    """Turn one Gmail message into the papers listed in the alert."""
    payload = raw_message.get("payload", {})
    html = _find_html_body(payload)
    if not html:
        return []

    message_id = raw_message.get("id", "")
    received_at = _parse_received_at(payload.get("headers", []))

    papers = []
    # Each paper is an <h3> holding the title link, followed by a div with the
    # "authors - journal, year" line and a div with the abstract snippet.
    for heading in BeautifulSoup(html, "html.parser").find_all("h3"):
        link = heading.find("a")
        if not link:
            continue

        authors_and_journal, snippet = _read_sibling_blocks(heading)
        authors_text, journal = _split_authors_and_journal(authors_and_journal)
        papers.append(
            ScholarPaper(
                title=link.get_text(strip=True),
                authors=[a.strip() for a in authors_text.split(",") if a.strip()],
                journal=journal.strip(),
                abstract=snippet,
                url=link.get("href", ""),
                source_email_id=message_id,
                received_at=received_at,
            )
        )
    return papers


def _find_html_body(payload: dict) -> str | None:
    """Depth-first search through MIME parts for the text/html body."""
    if payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        html = _find_html_body(part)
        if html:
            return html
    return None


def _parse_received_at(headers: list[dict]) -> datetime:
    """Read the Date header (e.g. 'Mon, 18 Mar 2026 10:00:00 +0000')."""
    for header in headers:
        if header["name"].lower() == "date":
            try:
                return parsedate_to_datetime(header["value"])
            except (ValueError, TypeError):
                break
    return datetime.now(UTC)


def _read_sibling_blocks(heading) -> tuple[str, str]:
    """(authors-and-journal line, abstract snippet) from the divs after a title."""
    authors_block = heading.find_next_sibling("div")
    if not authors_block:
        return "", ""

    colored_span = authors_block.find("span", style=lambda s: s and "color" in s)
    authors_and_journal = (colored_span or authors_block).get_text(strip=True)

    snippet_block = authors_block.find_next_sibling("div")
    snippet = snippet_block.get_text(separator=" ", strip=True) if snippet_block else ""
    return authors_and_journal, snippet


def _split_authors_and_journal(text: str) -> tuple[str, str]:
    """Split 'A, B\xa0- Journal Name, Year' into (authors, journal)."""
    for separator in ("\xa0- ", " - "):
        if separator in text:
            authors, journal = text.split(separator, 1)
            return authors, journal
    return text, ""
