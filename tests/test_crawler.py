from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import Mock, patch

import arxiv
import requests

from larklab.extract.crawler import crawl_arxiv


def _result(title: str):
    result = Mock()
    result.published = datetime.combine(
        date.today() - timedelta(days=1),
        time.min,
        tzinfo=UTC,
    )
    result.title = title
    result.authors = []
    result.summary = "abstract"
    result.doi = None
    result.get_short_id.return_value = "2605.12345v1"
    return result


def test_crawl_arxiv_continues_after_category_network_error():
    with patch("larklab.extract.crawler.arxiv.Client") as client_cls:
        client = client_cls.return_value
        client.results.side_effect = [
            requests.ConnectionError("dns failed"),
            [_result("Recovered Paper")],
        ]

        papers = crawl_arxiv(["cs.LG", "cs.AI"], days_back=2, max_results=5)

    assert [p.title for p in papers] == ["Recovered Paper"]


def test_crawl_arxiv_retries_category_after_rate_limit():
    with (
        patch("larklab.extract.crawler.time.sleep") as sleep,
        patch("larklab.extract.crawler.arxiv.Client") as client_cls,
    ):
        client = client_cls.return_value
        client.results.side_effect = [
            arxiv.HTTPError("https://export.arxiv.org/api/query", 0, 429),
            [_result("Recovered After Backoff")],
        ]

        papers = crawl_arxiv(["cs.LG"], days_back=2, max_results=5)

    sleep.assert_called_once()
    assert [p.title for p in papers] == ["Recovered After Backoff"]
