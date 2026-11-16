import logging
from datetime import UTC, date, datetime

from larklab.models import DailyDigest, ScholarPaper
from larklab.pipelines import scholar_digest as digest_pipeline
from larklab.pipelines.scholar_digest import (
    BATCH_GAP_HOURS,
    DigestOptions,
    DigestResult,
    group_into_batches,
    message_ids_to_trash,
    run_digest_pipeline,
)

HOUR_MS = 3600 * 1000


def test_group_into_batches_splits_on_gaps_and_puts_newest_first():
    messages = [
        ("old-1", 0),
        ("old-2", 1 * HOUR_MS),
        ("new-1", (1 + BATCH_GAP_HOURS + 1) * HOUR_MS),
    ]

    batches = group_into_batches(messages)

    assert [[mid for mid, _ in batch] for batch in batches] == [
        ["new-1"],
        ["old-1", "old-2"],
    ]
    assert group_into_batches([]) == []


def _scholar_paper(title: str, **fields) -> ScholarPaper:
    return ScholarPaper(
        title=title,
        authors=[],
        journal="",
        abstract="snippet",
        url=f"https://example.com/{title}",
        source_email_id="m1",
        received_at=datetime(2026, 11, 16, 8, tzinfo=UTC),
        **fields,
    )


class FakeGmail:
    def __init__(self, papers):
        self._papers = papers

    def list_message_ids(self, query, max_results, days_back):
        return ["m1", "m2"]

    def fetch_message_timestamps(self, message_ids):
        return [("m1", 0), ("m2", 10 * HOUR_MS)]  # two batches, m2 is newest

    def fetch_full_messages(self, message_ids):
        self.fetched = message_ids
        return [{"id": mid} for mid in message_ids]

    def parse_emails(self, raw_messages):
        return self._papers


def test_digest_pipeline_without_a_library_skips_scoring(config):
    gmail = FakeGmail(
        [_scholar_paper("Dup"), _scholar_paper("dup"), _scholar_paper("Other")]
    )

    result = run_digest_pipeline(
        gmail,
        config.db_path,
        DigestOptions(query="q", max_results=10, days_back=7, fetch_abstracts=False),
    )

    assert result.num_emails == 2
    assert result.num_parsed == 3
    assert [p.title for p in result.digests[0].papers] == ["Dup", "Other"]
    assert all(p.similar_papers is None for p in result.digests[0].papers)


def test_digest_pipeline_only_reads_the_requested_number_of_batches(config):
    gmail = FakeGmail([_scholar_paper("Only")])

    run_digest_pipeline(
        gmail,
        config.db_path,
        DigestOptions(
            query="q", max_results=10, days_back=7, fetch_abstracts=False, num_batches=1
        ),
    )

    assert gmail.fetched == ["m2"]  # newest batch only


def test_digest_pipeline_with_no_emails_returns_an_empty_result(config):
    class EmptyGmail:
        def list_message_ids(self, *args):
            return []

    result = run_digest_pipeline(
        EmptyGmail(), config.db_path, DigestOptions("q", 10, 7)
    )

    assert (result.digests, result.num_emails, result.num_parsed) == ([], 0, 0)


def test_digest_pipeline_scores_and_sorts_by_top_similarity(
    config, repository, make_paper, one_hot, monkeypatch
):
    repository.add(make_paper("Reference", embedding=one_hot(0)))
    scores = {"Weak": 0.2, "Strong": 0.9}
    monkeypatch.setattr(
        digest_pipeline,
        "find_similar_references",
        lambda papers, repo: [[("Reference", scores[p.title])] for p in papers],
    )
    gmail = FakeGmail([_scholar_paper("Weak"), _scholar_paper("Strong")])

    result = run_digest_pipeline(
        gmail,
        config.db_path,
        DigestOptions(query="q", max_results=10, days_back=7, fetch_abstracts=False),
    )

    papers = result.digests[0].papers
    assert [p.title for p in papers] == ["Strong", "Weak"]
    assert papers[0].similar_papers == [("Reference", 0.9)]


def test_only_emails_that_held_papers_are_listed_and_the_others_are_warned_about(
    config, caplog
):
    """m2 was read but parsed to nothing (a layout the parser may not know yet):
    it must not be offered for the trash, and the log says so."""
    gmail = FakeGmail([_scholar_paper("Only")])  # every paper comes from m1

    with caplog.at_level(logging.WARNING):
        result = run_digest_pipeline(
            gmail,
            config.db_path,
            DigestOptions(
                query="q", max_results=10, days_back=7, fetch_abstracts=False
            ),
        )

    assert result.num_emails == 2
    assert result.message_ids == ["m1"]
    assert "1 email(s) held no papers" in caplog.text


def _run_with_summaries(config, monkeypatch, summarize, titles):
    monkeypatch.setattr(digest_pipeline, "summarize_abstract", summarize)
    gmail = FakeGmail([_scholar_paper(title) for title in titles])
    result = run_digest_pipeline(
        gmail,
        config.db_path,
        DigestOptions(
            query="q",
            max_results=10,
            days_back=7,
            fetch_abstracts=False,
            summarize=True,
        ),
    )
    return {paper.title: paper.summary for paper in result.digests[0].papers}


def test_summaries_are_attached_when_asked_for(config, monkeypatch):
    summaries = _run_with_summaries(
        config,
        monkeypatch,
        lambda paper, model: f"• {paper.title} / {model}",
        ["A", "B"],
    )

    assert summaries == {"A": "• A / qwen3:8b", "B": "• B / qwen3:8b"}


def test_a_paper_that_cannot_be_summarized_keeps_its_abstract_and_the_rest_go_on(
    config, monkeypatch
):
    def summarize(paper, model):
        if paper.title == "Bad":
            raise RuntimeError("model hiccup")
        return "• ok"

    summaries = _run_with_summaries(config, monkeypatch, summarize, ["Bad", "Good"])

    assert summaries == {"Bad": "", "Good": "• ok"}  # empty: Slack shows the abstract


def test_summaries_stop_after_repeated_failures_instead_of_waiting_on_each_paper(
    config, monkeypatch
):
    calls = []

    def summarize(paper, model):
        calls.append(paper.title)
        raise ConnectionError("ollama is not running")

    titles = [f"P{number}" for number in range(10)]
    summaries = _run_with_summaries(config, monkeypatch, summarize, titles)

    assert len(calls) == digest_pipeline.MAX_SUMMARY_FAILURES_IN_A_ROW
    assert set(summaries.values()) == {""}  # the digest still goes out


def test_one_success_resets_the_failure_count(config, monkeypatch):
    failing = {"A", "B", "D", "E"}  # never three failures in a row

    def summarize(paper, model):
        if paper.title in failing:
            raise RuntimeError("hiccup")
        return "• ok"

    summaries = _run_with_summaries(
        config, monkeypatch, summarize, ["A", "B", "C", "D", "E", "F"]
    )

    assert summaries["C"] == summaries["F"] == "• ok"


def _digest(*titles: str, email: str = "m1") -> DailyDigest:
    papers = [_scholar_paper(title) for title in titles]
    for paper in papers:
        paper.source_email_id = email
    return DailyDigest(date=date(2026, 11, 16), papers=papers)


def test_everything_read_is_trashed_once_everything_was_delivered():
    sent = [_digest("A", email="m1"), _digest("B", email="m2")]
    result = DigestResult(
        digests=sent, num_emails=3, num_parsed=2, message_ids=["m1", "m2", "m3"]
    )

    # m3 only held repeats of papers in other emails: nothing of it is left to send
    assert message_ids_to_trash(result, sent) == ["m1", "m2", "m3"]


def test_emails_with_papers_in_an_undelivered_digest_are_kept():
    delivered, failed = _digest("A", email="m1"), _digest("B", email="m2")
    result = DigestResult(
        digests=[delivered, failed],
        num_emails=2,
        num_parsed=2,
        message_ids=["m1", "m2"],
    )

    assert message_ids_to_trash(result, [delivered]) == ["m1"]


def test_nothing_is_trashed_when_nothing_was_delivered():
    digest = _digest("A", email="m1")
    result = DigestResult(
        digests=[digest], num_emails=1, num_parsed=1, message_ids=["m1"]
    )

    assert message_ids_to_trash(result, []) == []
