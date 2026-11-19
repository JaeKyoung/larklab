"""Builders for the data classes the tests pass around. Every test file starts from
the same defaults and overrides what it cares about, so a field added to a class is
added here once, not in a dozen test files."""

from datetime import UTC, datetime

from larklab.models import Paper, Recommendation, ScholarPaper


def scholar_paper(title: str = "A Paper", **overrides) -> ScholarPaper:
    fields = {
        "title": title,
        "authors": ["Doe, Jane"],
        "journal": "Nature",
        "abstract": "An abstract.",
        "url": f"https://example.com/{title}",
        "source_email_id": "m1",
        "received_at": datetime(2026, 11, 16, 8, tzinfo=UTC),
    }
    return ScholarPaper(**{**fields, **overrides})


def recommendation(
    title: str = "A Paper", score: float = 0.8, **paper_overrides
) -> Recommendation:
    """A crawled paper (an arXiv one unless overridden) with one similar reference."""
    fields = {
        "title": title,
        "authors": ["A"],
        "journal": "arXiv",
        "abstract": "abstract",
        "doi": f"10.48550/arXiv.{title}",
        "source": "arxiv",
    }
    paper = Paper(**{**fields, **paper_overrides})
    return Recommendation(paper=paper, similar_papers=[("Reference", score)])
