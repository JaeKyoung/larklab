"""CLI command for paper recommendations."""

from functools import partial
from pathlib import Path

import click

from larklab.config import load_config
from larklab.library.repository import PaperRepository
from larklab.outputs.slack.recommendations import send_recommendations_to_slack
from larklab.outputs.terminal import print_recommendations
from larklab.pipelines.paper_recommendations import (
    RECOMMEND_SOURCES,
    run_recommendations,
)


@click.command("recommend")
@click.argument("sources", nargs=-1, type=click.Choice(RECOMMEND_SOURCES))
@click.option(
    "--categories",
    "-c",
    default=None,
    help="Comma-separated categories, or journals for pubmed "
    "(needs exactly one source)",
)
@click.option(
    "--days-back",
    "-d",
    default=1,
    type=click.IntRange(min=1),
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
def recommend(sources, categories, days_back, top_n, channel, threshold, no_slack):
    """Recommend papers from arXiv, bioRxiv and PubMed based on your reference library.

    Name the sources to read (`recommend arxiv biorxiv`); with none, all are read.
    """
    sources = list(sources) or list(RECOMMEND_SOURCES)
    if categories and len(set(sources)) != 1:
        raise click.UsageError(
            f"--categories needs exactly one source ({', '.join(RECOMMEND_SOURCES)})"
        )

    config = load_config()
    send = (
        None
        if no_slack
        else partial(
            send_recommendations_to_slack,
            token=config.slack_bot_token,
            channel=channel,
        )
    )
    with PaperRepository(config.db_path) as repository:
        run = run_recommendations(
            repository,
            sources=sources,
            categories=[c.strip() for c in categories.split(",")]
            if categories
            else None,
            days_back=days_back,
            top_n=top_n,
            threshold=threshold,
            progress_path=Path(config.crawl_progress_path),
            outbox_path=Path(config.outbox_path),
            send=send,
        )

    if run.shown.recommendations:
        print_recommendations(run.shown)
    if run.undelivered:
        click.echo(
            f"{len(run.undelivered)} recommendation(s) could not be posted to Slack; "
            "they will be sent with the next run."
        )
