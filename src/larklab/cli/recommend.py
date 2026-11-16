"""CLI command for paper recommendations."""

from dataclasses import replace

import click

from larklab.config import (
    CRAWL_PROGRESS_PATH,
    OUTBOX_PATH,
    load_config,
)
from larklab.library.repository import PaperRepository
from larklab.outputs.slack.recommendations import send_recommendations_to_slack
from larklab.outputs.terminal import print_recommendations
from larklab.pipelines.crawl_progress import advance_progress, load_progress
from larklab.pipelines.outbox import (
    load_outbox,
    merge_recommendations,
    save_outbox,
)
from larklab.pipelines.paper_recommendations import RECOMMEND_SOURCES, recommend_papers


@click.command("recommend")
@click.argument(
    "source",
    required=False,
    default=None,
    type=click.Choice(RECOMMEND_SOURCES),
)
@click.option(
    "--categories",
    "-c",
    default=None,
    help="Comma-separated categories (requires source)",
)
@click.option(
    "--days-back",
    "-d",
    default=1,
    help="Days to look back on the first run (later runs resume where the last "
    "run stopped)",
    show_default=True,
)
@click.option(
    "--top-n", "-n", default=20, help="Number of recommendations", show_default=True
)
@click.option(
    "--channel",
    default="journal-club",
    help="Slack channel to post recommendations",
    show_default=True,
)
@click.option(
    "--threshold",
    "-t",
    default=0.5,
    help="Minimum similarity score",
    show_default=True,
)
@click.option(
    "--no-slack",
    is_flag=True,
    help="Skip sending to Slack (print only; changes no saved state)",
)
def recommend(source, categories, days_back, top_n, channel, threshold, no_slack):
    """Recommend papers from arXiv or bioRxiv based on your reference library."""
    if categories and not source:
        raise click.UsageError(
            "--categories requires a source argument (arxiv or biorxiv)"
        )

    config = load_config()
    with PaperRepository(config.db_path) as repository:
        result = recommend_papers(
            repository,
            sources=[source] if source else list(RECOMMEND_SOURCES),
            categories=[c.strip() for c in categories.split(",")]
            if categories
            else None,
            days_back=days_back,
            top_n=top_n,
            threshold=threshold,
            since=load_progress(CRAWL_PROGRESS_PATH),
        )

    # Recommendations Slack could not take earlier go out together with the new ones.
    outgoing = replace(
        result,
        recommendations=merge_recommendations(
            load_outbox(OUTBOX_PATH), result.recommendations
        ),
    )
    if no_slack:  # a dry run: show everything, remember nothing
        if outgoing.recommendations:
            print_recommendations(outgoing)
        return

    undelivered = (
        send_recommendations_to_slack(
            outgoing, token=config.slack_bot_token, channel=channel
        )
        if outgoing.recommendations
        else []
    )
    if outgoing.recommendations:
        print_recommendations(outgoing)

    # Keep what failed first, then move on: nothing may be lost in between.
    save_outbox(OUTBOX_PATH, undelivered)
    advance_progress(CRAWL_PROGRESS_PATH, result.newest_published)
    if undelivered:
        click.echo(
            f"{len(undelivered)} recommendation(s) could not be posted to Slack; "
            "they will be sent with the next run."
        )
