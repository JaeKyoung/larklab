from pathlib import Path

import click

from larklab.config import load_config
from larklab.outputs.digest_json import write_digest_json
from larklab.outputs.slack.digest import send_digest_to_slack
from larklab.outputs.terminal import print_digest
from larklab.pipelines.scholar_digest import (
    DigestOptions,
    message_ids_to_trash,
    run_digest_pipeline,
)
from larklab.processing.summarizer import DEFAULT_SUMMARY_MODEL
from larklab.sources.gmail.client import GmailClient


@click.command()
@click.option(
    "--max-results",
    default=200,
    help="Maximum number of emails to fetch",
    show_default=True,
)
@click.option(
    "--days-back",
    default=7,
    help="How many days back to search",
    show_default=True,
)
@click.option(
    "--model",
    default=DEFAULT_SUMMARY_MODEL,
    help="Ollama model for summarization",
    show_default=True,
)
@click.option(
    "--summary",
    is_flag=True,
    help="Summarize abstracts with AI (Ollama)",
)
@click.option(
    "--channel",
    default="journal-club",
    help="Slack channel to post digest",
    show_default=True,
)
@click.option(
    "--query",
    default="from:scholaralerts-noreply@google.com",
    help="Gmail search query",
    show_default=True,
)
@click.option(
    "--no-fetch-abstracts",
    is_flag=True,
    help="Skip fetching full abstracts from paper URLs",
)
@click.option(
    "--cleanup",
    is_flag=True,
    help="Trash the processed emails once the digest was delivered",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Show details of trashed emails",
)
@click.option(
    "--batches",
    default=None,
    type=int,
    help="Process only the latest N batches (default: all)",
)
@click.option(
    "--no-slack",
    is_flag=True,
    help="Skip sending digest to Slack (print only)",
)
@click.option(
    "--output-json",
    default=None,
    type=click.Path(),
    help="Also write digest results as JSON to this path",
)
def digest(
    max_results,
    days_back,
    model,
    summary,
    channel,
    query,
    no_fetch_abstracts,
    cleanup,
    verbose,
    batches,
    no_slack,
    output_json,
):
    """Fetch Scholar emails, summarize, and send digest to Slack"""
    config = load_config()
    gmail = GmailClient(config)
    result = run_digest_pipeline(
        gmail,
        config.db_path,
        DigestOptions(
            query=query,
            max_results=max_results,
            days_back=days_back,
            fetch_abstracts=not no_fetch_abstracts,
            summarize=summary,
            summary_model=model,
            num_batches=batches,
        ),
    )

    if not result.digests:
        click.echo("No papers found. Nothing to send.")
        return

    if output_json:
        write_digest_json(
            Path(output_json),
            result.digests,
            num_emails=result.num_emails,
            num_parsed=result.num_parsed,
        )
        click.echo(f"Wrote JSON digest to {output_json}")

    if no_slack:
        print_digest(result.digests)
        sent_digests = result.digests
    else:
        sent_digests = send_digest_to_slack(
            result.digests, token=config.slack_bot_token, channel=channel
        )

    if not cleanup:
        return
    if not sent_digests:
        click.echo("Slack delivery failed — skipping email cleanup.")
        return
    trashed = gmail.trash_messages(
        message_ids_to_trash(result, sent_digests), verbose=verbose
    )
    click.echo(f"Trashed {len(trashed)} processed emails.")
    if len(sent_digests) < len(result.digests):
        click.echo(
            f"{len(result.digests) - len(sent_digests)} digest(s) were not delivered "
            "in full; the emails with their papers stay in the inbox."
        )
