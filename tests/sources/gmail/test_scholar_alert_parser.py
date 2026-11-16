import base64
from datetime import UTC, datetime

from larklab.sources.gmail.scholar_alert_parser import parse_scholar_email

ALERT_HTML = """
<html><body>
<h3><a href="https://example.com/p1">Paper One</a></h3>
<div><span style="color:#006621">J Doe, R Roe\xa0- Nature, 2026</span></div>
<div>Snippet about proteins</div>
<h3><a href="https://example.com/p2">Paper Two</a></h3>
<div>Plain Author - Cell</div>
<div>Another snippet</div>
<h3>A heading without a link</h3>
</body></html>
"""


def _message(html: str | None, date: str = "Mon, 18 Mar 2026 10:00:00 +0000") -> dict:
    parts = [{"mimeType": "text/plain", "body": {"data": ""}}]
    if html is not None:
        encoded = base64.urlsafe_b64encode(html.encode()).decode()
        parts.append({"mimeType": "text/html", "body": {"data": encoded}})
    return {
        "id": "msg-1",
        "payload": {
            "headers": [{"name": "Date", "value": date}],
            "mimeType": "multipart/alternative",
            "parts": parts,
        },
    }


def test_parses_titles_authors_journals_and_snippets():
    first, second = parse_scholar_email(_message(ALERT_HTML))

    assert first.title == "Paper One"
    assert first.url == "https://example.com/p1"
    assert first.authors == ["J Doe", "R Roe"]
    assert first.journal == "Nature, 2026"
    assert first.abstract == "Snippet about proteins"
    assert first.source_email_id == "msg-1"
    assert first.received_at.year == 2026

    assert second.authors == ["Plain Author"]
    assert second.journal == "Cell"


def test_headings_without_a_link_are_ignored():
    titles = [p.title for p in parse_scholar_email(_message(ALERT_HTML))]
    assert titles == ["Paper One", "Paper Two"]


def test_message_without_html_has_no_papers():
    assert parse_scholar_email(_message(None)) == []


def test_bad_date_header_falls_back_to_now():
    paper = parse_scholar_email(_message(ALERT_HTML, date="not a date"))[0]
    assert abs((datetime.now(UTC) - paper.received_at).total_seconds()) < 60
