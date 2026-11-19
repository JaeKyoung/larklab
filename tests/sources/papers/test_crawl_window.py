from datetime import UTC, date, datetime

from larklab.sources.papers import MAX_CATCH_UP_DAYS, crawl_window

END = date(2026, 11, 15)


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def test_without_a_resume_point_it_is_the_last_days_up_to_the_end():
    assert crawl_window(END, 1, None) == (END, END)
    assert crawl_window(END, 3, None) == (date(2026, 11, 13), END)


def test_with_a_resume_point_it_starts_on_the_day_after():
    assert crawl_window(END, 1, _at(date(2026, 11, 12))) == (date(2026, 11, 13), END)


def test_nothing_is_new_when_the_resume_point_is_already_at_the_end():
    assert crawl_window(END, 1, _at(END)) is None
    assert crawl_window(END, 1, _at(date(2026, 11, 20))) is None


def test_catching_up_never_goes_back_more_than_a_week():
    start, end = crawl_window(END, 1, _at(date(2026, 9, 1)))

    assert end == END
    assert (end - start).days == MAX_CATCH_UP_DAYS - 1
