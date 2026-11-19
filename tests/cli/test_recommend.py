"""The `recommend` command only wires options to the pipeline; nothing is posted.
The delivery rules (outbox, resume points) are tested in tests/pipelines."""

import importlib
from pathlib import Path

import pytest
from builders import recommendation
from click.testing import CliRunner

from larklab.models import RecommendationResult
from larklab.pipelines.paper_recommendations import RecommendationRun

recommend_cli = importlib.import_module("larklab.cli.recommend")


def _run_with(*titles: str, undelivered=()) -> RecommendationRun:
    recommendations = [recommendation(title) for title in titles]
    shown = RecommendationResult(recommendations, candidate_counts={})
    return RecommendationRun(shown, list(undelivered))


@pytest.fixture
def invoke(config, monkeypatch):
    """Run `recommend` with a fake pipeline and a fake Slack: nothing is posted."""
    seen = {"options": None, "slack": []}
    behaviour = {"run": _run_with("New")}

    def fake_run(repository, **options):
        seen["options"] = options
        if options["send"] is not None:  # a real run asks Slack to post
            options["send"](behaviour["run"].shown)
        return behaviour["run"]

    def fake_slack(result, **kwargs):
        seen["slack"].append(kwargs)
        return []

    monkeypatch.setattr(recommend_cli, "load_config", lambda: config)
    monkeypatch.setattr(recommend_cli, "run_recommendations", fake_run)
    monkeypatch.setattr(recommend_cli, "send_recommendations_to_slack", fake_slack)

    def run(*args, outcome=None):
        if outcome is not None:
            behaviour["run"] = outcome
        result = CliRunner().invoke(recommend_cli.recommend, list(args))
        return result, seen

    return run


def test_the_pipeline_gets_the_state_files_from_the_config(invoke, config):
    _, seen = invoke()

    assert seen["options"]["progress_path"] == Path(config.crawl_progress_path)
    assert seen["options"]["outbox_path"] == Path(config.outbox_path)


def test_recommendations_are_printed(invoke):
    result, _ = invoke(outcome=_run_with("Alpha", "Beta"))

    assert "Alpha" in result.output and "Beta" in result.output


def test_nothing_to_show_prints_nothing(invoke):
    result, _ = invoke(outcome=_run_with())

    assert result.output == ""


def test_recommendations_slack_refused_are_reported(invoke):
    refused = _run_with("Sent", "Refused").shown.recommendations[1:]

    result, _ = invoke(outcome=_run_with("Sent", "Refused", undelivered=refused))

    assert "1 recommendation(s) could not be posted" in result.output


def test_the_channel_and_token_reach_slack(invoke, config):
    _, seen = invoke("--channel", "reading-group")

    assert seen["slack"] == [
        {"token": config.slack_bot_token, "channel": "reading-group"}
    ]


def test_a_dry_run_gives_the_pipeline_no_way_to_send(invoke):
    result, seen = invoke("--no-slack")

    assert seen["options"]["send"] is None
    assert seen["slack"] == []
    assert "New" in result.output  # but everything is still printed


def test_without_a_source_every_source_is_read(invoke):
    _, seen = invoke()

    assert seen["options"]["sources"] == ["arxiv", "biorxiv", "pubmed"]


def test_sources_can_be_chosen_and_are_read_in_the_order_given(invoke):
    _, seen = invoke("biorxiv", "arxiv")
    assert seen["options"]["sources"] == ["biorxiv", "arxiv"]

    _, seen = invoke("pubmed")
    assert seen["options"]["sources"] == ["pubmed"]


def test_an_unknown_source_is_refused(invoke):
    result, seen = invoke("medrxiv")

    assert result.exit_code == 2
    assert seen["options"] is None  # nothing was crawled


@pytest.mark.parametrize("sources", [[], ["arxiv", "pubmed"]])
def test_categories_need_exactly_one_source(invoke, sources):
    result, seen = invoke(*sources, "--categories", "cs.LG")

    assert result.exit_code == 2
    assert "exactly one source" in result.output
    assert seen["options"] is None


@pytest.mark.parametrize("days", ["0", "-2"])
def test_days_back_must_be_at_least_one(invoke, days):
    result, seen = invoke("--days-back", days)

    assert result.exit_code == 2
    assert seen["options"] is None


def test_categories_go_with_a_single_source(invoke):
    result, seen = invoke("pubmed", "--categories", "Protein science, Bioinformatics")

    assert result.exit_code == 0
    assert seen["options"]["sources"] == ["pubmed"]
    assert seen["options"]["categories"] == ["Protein science", "Bioinformatics"]
