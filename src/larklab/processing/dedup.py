from collections import defaultdict
from datetime import date, datetime

from larklab.models import DailyDigest, ScholarPaper


def dedup_and_group_by_date(papers: list[ScholarPaper]) -> list[DailyDigest]:
    """Drop repeated titles, then group papers by local received date (newest first).

    Only titles identical up to case and surrounding whitespace count as repeats:
    the digest must never silently merge two distinct papers.
    """
    seen_titles: set[str] = set()
    papers_by_date: dict[date, list[ScholarPaper]] = defaultdict(list)

    for paper in papers:
        title_key = paper.title.lower().strip()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        received_at = paper.received_at or datetime.now().astimezone()
        papers_by_date[received_at.astimezone().date()].append(paper)

    return [
        DailyDigest(date=day, papers=day_papers)
        for day, day_papers in sorted(papers_by_date.items(), reverse=True)
    ]
