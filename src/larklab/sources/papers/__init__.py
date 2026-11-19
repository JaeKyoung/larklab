"""One module per paper source; `metadata_lookup` merges them."""

from datetime import date, datetime, timedelta

# How far back a crawler catches up after missed days. Longer outages lose the
# oldest papers rather than flooding Slack with a month of recommendations.
MAX_CATCH_UP_DAYS = 7


def crawl_window(
    end: date, days_back: int, since: datetime | None
) -> tuple[date, date] | None:
    """The first and last day a day-by-day crawler reads: the last `days_back` days
    up to `end`, or, with `since`, from the day after it (at most a week back).
    None when `since` is already at `end`, so there is nothing new."""
    start = end - timedelta(days=days_back - 1)
    if since:
        resume_day = since.date() + timedelta(days=1)
        start = max(resume_day, end - timedelta(days=MAX_CATCH_UP_DAYS - 1))
    return (start, end) if start <= end else None
