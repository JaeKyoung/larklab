"""`recommend` is a cron job: it must not lose or repeat papers. Nothing is posted."""

from datetime import UTC, datetime, timedelta

import pytest
from builders import recommendation

from larklab.models import Recommendation, RecommendationResult, SourceProgress
from larklab.pipelines import paper_recommendations as pipeline
from larklab.pipelines.crawl_progress import advance_progress, load_progress
from larklab.pipelines.outbox import load_outbox, save_outbox
from larklab.pipelines.paper_recommendations import run_recommendations
from larklab.utils.files import LockBusy, exclusive_lock

NOW = datetime.now(UTC)
NEWEST = NOW - timedelta(days=1)
EARLIER = NOW - timedelta(days=2)


def _recommendation(title: str, score: float = 0.8, doi: str | None = None):
    extra = {"doi": doi} if doi else {}
    return recommendation(title, score, published_at=NEWEST, **extra)


def _result(*recommendations: Recommendation, newest=NEWEST) -> RecommendationResult:
    return RecommendationResult(
        recommendations=list(recommendations),
        candidate_counts={},
        progress={"arxiv": SourceProgress(newest)} if newest else {},
    )


@pytest.fixture
def run(repository, monkeypatch, tmp_path):
    """Run the delivery with a fake crawl-and-score and a fake Slack."""
    progress_path, outbox_path = tmp_path / "progress.json", tmp_path / "outbox.json"
    seen = {"progress": None, "sent": [], "send_calls": 0}
    behaviour = {"result": _result(_recommendation("New")), "undelivered": None}

    def fake_recommend(repository, **options):
        seen["progress"] = options["progress"]
        return behaviour["result"]

    def fake_send(result):
        seen["send_calls"] += 1
        seen["sent"].append([r.paper.title for r in result.recommendations])
        refuse = behaviour["undelivered"]
        return refuse(result) if refuse else []

    monkeypatch.setattr(pipeline, "recommend_papers", fake_recommend)

    def execute(*, dry_run=False, **settings):
        behaviour.update(settings)
        shown = run_recommendations(
            repository,
            sources=["arxiv"],
            categories=None,
            days_back=1,
            top_n=20,
            threshold=0.5,
            progress_path=progress_path,
            outbox_path=outbox_path,
            send=None if dry_run else fake_send,
        )
        return shown, seen

    execute.progress_path, execute.outbox_path = progress_path, outbox_path
    return execute


def test_a_delivered_run_moves_the_resume_point_and_leaves_nothing_waiting(run):
    outcome, seen = run()

    assert [r.paper.title for r in outcome.shown.recommendations] == ["New"]
    assert outcome.undelivered == []
    assert seen["sent"] == [["New"]]
    assert load_progress(run.progress_path) == {"arxiv": SourceProgress(NEWEST)}
    assert not run.outbox_path.exists()


def test_recommendations_slack_refused_are_kept_and_the_run_still_moves_on(run):
    outcome, _ = run(
        result=_result(_recommendation("Sent"), _recommendation("Refused")),
        undelivered=lambda shown: [
            r for r in shown.recommendations if r.paper.title == "Refused"
        ],
    )

    assert [r.paper.title for r in outcome.undelivered] == ["Refused"]
    assert [r.paper.title for r in load_outbox(run.outbox_path)] == ["Refused"]
    # safe: what was refused is queued
    assert load_progress(run.progress_path) == {"arxiv": SourceProgress(NEWEST)}


def test_waiting_recommendations_go_out_with_the_next_run(run):
    save_outbox(run.outbox_path, [_recommendation("Waiting", score=0.9)])

    _, seen = run(result=_result(_recommendation("New", score=0.6)))

    assert seen["sent"] == [["Waiting", "New"]]  # together, best first
    assert not run.outbox_path.exists()  # delivered, so it is deleted


def test_waiting_recommendations_are_sent_even_when_nothing_new_was_found(run):
    save_outbox(run.outbox_path, [_recommendation("Waiting")])

    _, seen = run(result=_result(newest=None))

    assert seen["sent"] == [["Waiting"]]
    assert not run.outbox_path.exists()


def test_a_waiting_paper_that_was_added_to_the_library_since_is_not_sent(
    run, repository, make_paper, one_hot
):
    """It was queued when Slack failed; meanwhile the user added it as a reference."""
    save_outbox(
        run.outbox_path,
        [_recommendation("Known now", doi="10.1/known"), _recommendation("Still new")],
    )
    repository.add(make_paper("Known now", doi="10.1/known", embedding=one_hot(0)))

    _, seen = run(result=_result(newest=None))

    assert seen["sent"] == [["Still new"]]
    assert not run.outbox_path.exists()


def test_nothing_new_and_nothing_waiting_posts_no_empty_thread(run):
    _, seen = run(result=_result())

    assert seen["send_calls"] == 0
    assert load_progress(run.progress_path) == {"arxiv": SourceProgress(NEWEST)}


def test_a_dry_run_shows_everything_and_remembers_nothing(run):
    save_outbox(run.outbox_path, [_recommendation("Waiting")])

    outcome, seen = run(dry_run=True)

    assert {r.paper.title for r in outcome.shown.recommendations} == {"Waiting", "New"}
    assert seen["send_calls"] == 0
    assert load_progress(run.progress_path) == {}
    assert [r.paper.title for r in load_outbox(run.outbox_path)] == ["Waiting"]


def test_earlier_progress_is_handed_to_the_pipeline_and_never_rewound(run):
    before = {"arxiv": SourceProgress(NEWEST), "biorxiv": SourceProgress(EARLIER)}
    advance_progress(run.progress_path, before)

    _, seen = run(result=_result(newest=EARLIER))

    assert seen["progress"] == before
    assert load_progress(run.progress_path) == before


def test_a_source_that_was_not_read_completely_keeps_its_old_resume_point(run):
    advance_progress(run.progress_path, {"arxiv": SourceProgress(EARLIER)})

    run(result=_result(newest=None))  # the pipeline left arxiv out: crawl incomplete

    assert load_progress(run.progress_path) == {"arxiv": SourceProgress(EARLIER)}


def test_a_run_that_saves_refuses_to_start_while_another_one_is_going(run):
    """Regression: two runs read the state files, then each wrote its own version, so
    one run's waiting Slack recommendations could be erased by the other."""
    with exclusive_lock(run.progress_path.with_name("recommend.lock")):
        with pytest.raises(LockBusy):
            run()
        _, seen = run(dry_run=True)  # looking changes nothing, so it may go on

    assert seen["send_calls"] == 0
    assert load_progress(run.progress_path) == {}
    assert load_outbox(run.outbox_path) == []


def test_the_lock_is_free_again_after_a_run_even_a_failed_one(run):
    run()

    def refuse_to_deliver(result):
        raise OSError("network down")

    with pytest.raises(OSError):
        run(undelivered=refuse_to_deliver)

    run(undelivered=None)  # would raise LockBusy if either run had kept the lock
