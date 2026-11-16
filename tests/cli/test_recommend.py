"""`recommend` is a cron job: it must not lose or repeat papers. Nothing is posted."""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner

from larklab.models import Paper, Recommendation, RecommendationResult
from larklab.pipelines.crawl_progress import advance_progress, load_progress
from larklab.pipelines.outbox import load_outbox, save_outbox

recommend_cli = importlib.import_module("larklab.cli.recommend")

NOW = datetime.now(UTC)
NEWEST = NOW - timedelta(days=1)
EARLIER = NOW - timedelta(days=2)


def _recommendation(title: str, score: float = 0.8) -> Recommendation:
    paper = Paper(
        title=title,
        authors=["A"],
        journal="arXiv",
        abstract="abs",
        doi=f"10.48550/arXiv.{title}",
        published_at=NEWEST,
    )
    return Recommendation(paper=paper, similar_papers=[("Reference", score)])


def _result(*recommendations: Recommendation, newest=NEWEST) -> RecommendationResult:
    return RecommendationResult(
        recommendations=list(recommendations),
        candidate_counts={},
        newest_published={"arxiv": newest} if newest else {},
    )


@pytest.fixture
def invoke(config, monkeypatch, tmp_path):
    """Run `recommend` with a fake pipeline and a fake Slack: nothing is posted."""
    progress_path, outbox_path = tmp_path / "progress.json", tmp_path / "outbox.json"
    seen = {"since": None, "sent": []}
    behaviour = {"result": _result(_recommendation("New")), "undelivered": []}

    def fake_recommend(repository, **options):
        seen["since"] = options["since"]
        return behaviour["result"]

    def fake_slack(result, **kwargs):
        seen["sent"].append([r.paper.title for r in result.recommendations])
        return (
            behaviour["undelivered"](result)
            if callable(behaviour["undelivered"])
            else []
        )

    monkeypatch.setattr(recommend_cli, "load_config", lambda: config)
    monkeypatch.setattr(recommend_cli, "CRAWL_PROGRESS_PATH", progress_path)
    monkeypatch.setattr(recommend_cli, "OUTBOX_PATH", outbox_path)
    monkeypatch.setattr(recommend_cli, "recommend_papers", fake_recommend)
    monkeypatch.setattr(recommend_cli, "send_recommendations_to_slack", fake_slack)

    def run(*args, **settings):
        behaviour.update(settings)
        result = CliRunner().invoke(recommend_cli.recommend, list(args))
        return result, seen

    run.progress_path, run.outbox_path = progress_path, outbox_path
    return run


def test_a_delivered_run_moves_the_resume_point_and_leaves_nothing_waiting(invoke):
    result, seen = invoke()

    assert "New" in result.output
    assert seen["sent"] == [["New"]]
    assert load_progress(invoke.progress_path) == {"arxiv": NEWEST}
    assert not invoke.outbox_path.exists()


def test_recommendations_slack_refused_are_kept_and_the_run_still_moves_on(invoke):
    result, _ = invoke(
        result=_result(_recommendation("Sent"), _recommendation("Refused")),
        undelivered=lambda outgoing: [
            r for r in outgoing.recommendations if r.paper.title == "Refused"
        ],
    )

    assert [r.paper.title for r in load_outbox(invoke.outbox_path)] == ["Refused"]
    assert load_progress(invoke.progress_path) == {
        "arxiv": NEWEST
    }  # safe: it is queued
    assert "1 recommendation(s) could not be posted" in result.output


def test_waiting_recommendations_go_out_with_the_next_run(invoke):
    save_outbox(invoke.outbox_path, [_recommendation("Waiting", score=0.9)])

    _, seen = invoke(result=_result(_recommendation("New", score=0.6)))

    assert seen["sent"] == [["Waiting", "New"]]  # together, best first
    assert not invoke.outbox_path.exists()  # delivered, so it is deleted


def test_waiting_recommendations_are_sent_even_when_nothing_new_was_found(invoke):
    save_outbox(invoke.outbox_path, [_recommendation("Waiting")])

    _, seen = invoke(result=_result(newest=None))

    assert seen["sent"] == [["Waiting"]]
    assert not invoke.outbox_path.exists()


def test_nothing_new_and_nothing_waiting_posts_no_empty_thread(invoke):
    _, seen = invoke(result=_result())

    assert seen["sent"] == []
    assert load_progress(invoke.progress_path) == {"arxiv": NEWEST}  # crawl was fine


def test_a_dry_run_prints_everything_and_remembers_nothing(invoke):
    save_outbox(invoke.outbox_path, [_recommendation("Waiting")])

    result, seen = invoke("--no-slack")

    assert "Waiting" in result.output and "New" in result.output
    assert seen["sent"] == []
    assert load_progress(invoke.progress_path) == {}
    assert [r.paper.title for r in load_outbox(invoke.outbox_path)] == ["Waiting"]


def test_earlier_progress_is_handed_to_the_pipeline_and_never_rewound(invoke):
    advance_progress(invoke.progress_path, {"arxiv": NEWEST, "biorxiv": EARLIER})

    _, seen = invoke(result=_result(newest=EARLIER))

    assert seen["since"] == {"arxiv": NEWEST, "biorxiv": EARLIER}
    assert load_progress(invoke.progress_path) == {"arxiv": NEWEST, "biorxiv": EARLIER}


def test_a_source_that_was_not_read_completely_keeps_its_old_resume_point(invoke):
    advance_progress(invoke.progress_path, {"arxiv": EARLIER})

    invoke(result=_result(newest=None))  # the pipeline left arxiv out: crawl incomplete

    assert load_progress(invoke.progress_path) == {"arxiv": EARLIER}


def test_categories_need_a_source(invoke):
    result, _ = invoke("--categories", "cs.LG")

    assert result.exit_code == 2
    assert "requires a source" in result.output
