"""The Slack senders against a fake WebClient: nothing is ever really posted."""

from datetime import UTC, date, datetime

import pytest
from builders import recommendation, scholar_paper
from slack_sdk.errors import SlackApiError

from larklab.models import (
    DailyDigest,
    Recommendation,
    RecommendationResult,
    ScholarPaper,
)
from larklab.outputs.slack import digest as slack_digest
from larklab.outputs.slack import recommendations as slack_recommendations
from larklab.outputs.slack.paper_thread import (
    PaperCard,
    post_message,
    post_paper_thread,
)


class _ErrorResponse(dict):
    headers = {"Retry-After": "7"}


def _slack_error(code: str) -> SlackApiError:
    return SlackApiError("failed", _ErrorResponse(error=code))


class FakeSlack:
    """Records posts; `fail_with` maps an exact message/attachment title to an error."""

    def __init__(self, fail_with=None):
        self.posts = []
        self.fail_with = fail_with or {}
        self._clock = 0

    def chat_postMessage(self, **kwargs):
        attachments = kwargs.get("attachments")
        key = attachments[0]["title"] if attachments else kwargs["text"]
        if key in self.fail_with:
            failure = self.fail_with[key]
            raise failure if isinstance(failure, Exception) else _slack_error(failure)
        self._clock += 1
        self.posts.append(kwargs)
        return {"ts": f"ts-{self._clock}"}


def _card(title: str) -> PaperCard:
    return PaperCard(
        title=title,
        url="https://doi.org/10.1/x",
        journal="Nature",
        authors=["A"],
        text="t",
    )


# --- threads ------------------------------------------------------------------


def test_headline_then_one_threaded_card_per_paper():
    slack = FakeSlack()

    result = post_paper_thread(
        slack, "journal-club", "Headline", [_card("One"), _card("Two")]
    )

    assert (result.started, result.posted, result.failed_indexes) == (True, 2, [])
    headline, first, second = slack.posts
    assert headline["text"] == "Headline" and headline["thread_ts"] is None
    assert first["thread_ts"] == second["thread_ts"] == "ts-1"
    assert [p["attachments"][0]["title"] for p in (first, second)] == ["One", "Two"]


def test_a_failed_card_is_reported_in_the_thread_and_the_rest_still_go_out():
    slack = FakeSlack(fail_with={"Two": "invalid_blocks"})

    result = post_paper_thread(
        slack, "journal-club", "Headline", [_card("One"), _card("Two"), _card("Three")]
    )

    assert (result.started, result.posted, result.failed_indexes) == (True, 2, [1])
    notice = slack.posts[-1]["text"]
    assert "1 paper card(s) failed" in notice and "Two" in notice


def test_nothing_is_posted_under_a_headline_that_failed():
    slack = FakeSlack(fail_with={"Headline": "channel_not_found"})

    result = post_paper_thread(
        slack, "nowhere", "Headline", [_card("One"), _card("Two")]
    )

    assert (result.started, result.posted) == (False, 0)
    assert result.failed_indexes == [0, 1]  # every card is still owed
    assert slack.posts == []


def test_a_rate_limit_waits_as_told_and_then_succeeds(sleeps):
    attempts = {"count": 0}

    class RateLimitedOnce(FakeSlack):
        def chat_postMessage(self, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise _slack_error("ratelimited")
            return super().chat_postMessage(**kwargs)

    assert post_message(RateLimitedOnce(), "c", "hello") == "ts-1"
    assert sleeps == [7]  # the Retry-After header


def test_other_errors_are_not_retried(sleeps):
    slack = FakeSlack(fail_with={"hello": "not_in_channel"})

    assert post_message(slack, "c", "hello") is None
    assert sleeps == []


def test_a_network_error_is_a_failed_post_not_a_crash(sleeps):
    slack = FakeSlack(fail_with={"hello": ConnectionError("network is down")})

    assert post_message(slack, "c", "hello") is None
    assert sleeps == []  # not a rate limit: no waiting, no retry


def test_a_card_lost_to_a_network_error_is_reported_and_the_rest_go_out():
    slack = FakeSlack(fail_with={"Two": TimeoutError("timed out")})

    result = post_paper_thread(
        slack, "journal-club", "Headline", [_card("One"), _card("Two"), _card("Three")]
    )

    assert (result.started, result.posted, result.failed_indexes) == (True, 2, [1])


def test_gives_up_after_three_rate_limits(sleeps):
    slack = FakeSlack(fail_with={"hello": "ratelimited"})

    assert post_message(slack, "c", "hello") is None
    assert sleeps == [7, 7, 7]


# --- digest ---------------------------------------------------------------------


def _scholar_paper(title: str) -> ScholarPaper:
    return scholar_paper(
        title,
        authors=["A"],
        abstract="Full abstract.",
        url="https://doi.org/10.1/x",
        received_at=None,
    )


def test_digest_without_a_token_sends_nothing_and_builds_no_client(monkeypatch):
    monkeypatch.setattr(
        slack_digest, "WebClient", lambda **kw: pytest.fail("no client")
    )

    assert slack_digest.send_digest_to_slack([], token="", channel="c") == []


def test_digest_threads_use_the_summary_when_there_is_one(monkeypatch):
    slack = FakeSlack()
    monkeypatch.setattr(slack_digest, "WebClient", lambda **kw: slack)
    summarized = _scholar_paper("Summarized")
    summarized.summary = "• three bullets"
    digest = DailyDigest(
        date=date(2026, 11, 16), papers=[summarized, _scholar_paper("Plain")]
    )

    sent = slack_digest.send_digest_to_slack([digest], token="xoxb", channel="c")

    assert sent == [digest]
    assert slack.posts[0]["text"] == "*Scholar Digest — 2026-11-16*\n• 2 papers"
    texts = [p["attachments"][0]["text"] for p in slack.posts[1:]]
    assert texts == ["• three bullets", "Full abstract."]


def test_digest_whose_headline_failed_is_not_reported_as_sent(monkeypatch):
    headline = "*Scholar Digest — 2026-11-16*\n• 1 papers"
    slack = FakeSlack(fail_with={headline: "channel_not_found"})
    monkeypatch.setattr(slack_digest, "WebClient", lambda **kw: slack)
    digest = DailyDigest(date=date(2026, 11, 16), papers=[_scholar_paper("A")])

    assert slack_digest.send_digest_to_slack([digest], token="xoxb", channel="c") == []


def test_digest_with_a_failed_card_is_not_reported_as_sent(monkeypatch):
    """Regression: a digest whose headline went out counted as delivered, so
    `--cleanup` trashed the email of a paper that never reached Slack."""
    slack = FakeSlack(fail_with={"Lost": "invalid_blocks"})
    monkeypatch.setattr(slack_digest, "WebClient", lambda **kw: slack)
    digest = DailyDigest(
        date=date(2026, 11, 16),
        papers=[_scholar_paper("Posted"), _scholar_paper("Lost")],
    )

    assert slack_digest.send_digest_to_slack([digest], token="xoxb", channel="c") == []


# --- recommendations ----------------------------------------------------------------


def _recommendation(title: str, day: int) -> Recommendation:
    return recommendation(title, published_at=datetime(2026, 11, day, 12, tzinfo=UTC))


def _result(*recommendations: Recommendation) -> RecommendationResult:
    counts = {r.paper.published_date: {"arxiv": 4} for r in recommendations}
    return RecommendationResult(list(recommendations), counts)


def _headline(day: int, kept: int = 1) -> str:
    return f"*Paper Recommendations — 2026-11-{day}*\n• arxiv: {kept}/4"


@pytest.fixture
def fake_slack(monkeypatch):
    def install(**kwargs) -> FakeSlack:
        slack = FakeSlack(**kwargs)
        monkeypatch.setattr(slack_recommendations, "WebClient", lambda **kw: slack)
        return slack

    return install


def test_without_a_token_every_recommendation_is_still_owed(monkeypatch):
    monkeypatch.setattr(
        slack_recommendations, "WebClient", lambda **kw: pytest.fail("no client")
    )
    first, second = _recommendation("One", 13), _recommendation("Two", 12)

    owed = slack_recommendations.send_recommendations_to_slack(
        _result(first, second), token="", channel="c"
    )

    assert owed == [first, second]


def test_everything_posted_means_nothing_is_owed(fake_slack):
    slack = fake_slack()

    owed = slack_recommendations.send_recommendations_to_slack(
        _result(_recommendation("One", 13)), token="xoxb", channel="c"
    )

    assert owed == []
    assert slack.posts[0]["text"] == _headline(13)
    fields = slack.posts[1]["attachments"][0]["fields"]
    assert fields[1]["title"] == "Top 1 related paper (similarity: 0.800)"


def test_a_thread_that_could_not_be_started_is_owed_but_the_others_go_out(fake_slack):
    newer, older = _recommendation("Newer", 13), _recommendation("Older", 12)
    slack = fake_slack(fail_with={_headline(12): "channel_not_found"})

    owed = slack_recommendations.send_recommendations_to_slack(
        _result(newer, older), token="xoxb", channel="c"
    )

    assert owed == [older]  # the other date's thread was delivered
    assert [p["text"] for p in slack.posts if not p["attachments"]] == [_headline(13)]


def test_only_the_cards_that_failed_are_owed(fake_slack):
    first, second = _recommendation("One", 13), _recommendation("Two", 13)
    fake_slack(fail_with={"Two": "invalid_blocks"})

    owed = slack_recommendations.send_recommendations_to_slack(
        _result(first, second), token="xoxb", channel="c"
    )

    assert owed == [second]


def test_waiting_recommendations_do_not_show_an_impossible_ratio(fake_slack):
    """Papers carried over from an earlier run have no crawl count for their date."""
    slack = fake_slack()
    waiting = [_recommendation("A", 13), _recommendation("B", 13)]
    result = RecommendationResult(waiting, candidate_counts={})

    slack_recommendations.send_recommendations_to_slack(
        result, token="xoxb", channel="c"
    )

    assert (
        slack.posts[0]["text"] == "*Paper Recommendations — 2026-11-13*\n• arxiv: 2/2"
    )
