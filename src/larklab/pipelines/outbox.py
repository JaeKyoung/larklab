"""Recommendations Slack could not take, kept until a later run delivers them.

A failed post must not lose papers: `recommend` saves what was not delivered here,
sends it again together with the next run's recommendations, and the file shrinks
or disappears as soon as Slack accepts them.
"""

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from larklab.models import Paper, Recommendation
from larklab.utils.files import read_json_or, write_text_atomically

logger = logging.getLogger(__name__)

_MAX_AGE_DAYS = 14  # a paper this old is no longer worth recommending


def load_outbox(path: Path) -> list[Recommendation]:
    """Recommendations waiting for delivery; empty if there are none.

    A missing or unreadable file means "nothing waiting" — never an error.
    """
    waiting = read_json_or(
        path,
        _parse_entries,
        default=[],
        what="outbox",
    )
    oldest = datetime.now(UTC) - timedelta(days=_MAX_AGE_DAYS)
    return [
        rec
        for rec in waiting
        if rec.paper.published_at is None or rec.paper.published_at >= oldest
    ]


def save_outbox(path: Path, recommendations: list[Recommendation]) -> None:
    """Replace the waiting list; an empty list removes the file."""
    if not recommendations:
        path.unlink(missing_ok=True)
        return
    write_text_atomically(
        path,
        json.dumps(
            [_to_dict(rec) for rec in recommendations],
            ensure_ascii=False,
            indent=2,
            default=datetime.isoformat,
        ),
    )


def merge_recommendations(
    waiting: list[Recommendation], new: list[Recommendation]
) -> list[Recommendation]:
    """Waiting plus new, one entry per paper (the newest score wins), best first."""
    by_doi = {rec.paper.doi.lower(): rec for rec in [*waiting, *new]}
    return sorted(by_doi.values(), key=lambda rec: rec.score, reverse=True)


def _parse_entries(items: list[dict]) -> list[Recommendation]:
    """Every entry that can be read; a damaged one is skipped, not the whole file."""
    entries = []
    for item in items:
        try:
            entries.append(_from_dict(item))
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            logger.warning("Skipping an unreadable outbox entry: %s", error)
    return entries


def _to_dict(recommendation: Recommendation) -> dict:
    # asdict, so a field added to Paper later is saved without touching this file
    return {
        "paper": asdict(recommendation.paper),
        "similar_papers": recommendation.similar_papers,
    }


def _from_dict(item: dict) -> Recommendation:
    paper = item["paper"]
    published_at = paper.get("published_at")
    return Recommendation(
        paper=Paper(
            **{
                **paper,
                "published_at": datetime.fromisoformat(published_at)
                if published_at
                else None,
            }
        ),
        similar_papers=[(title, score) for title, score in item["similar_papers"]],
    )
