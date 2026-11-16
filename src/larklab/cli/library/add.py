"""db-add: fetch a paper, show a preview, and store it in the library."""

import click

from larklab.cli.library.field_edits import apply_overrides, reject_duplicate_titles
from larklab.config import load_config
from larklab.library.embedder import embed_paper
from larklab.library.repository import PaperRepository
from larklab.models import Paper
from larklab.outputs.terminal import print_paper_entry, print_paper_preview
from larklab.sources.papers.metadata_lookup import fetch_paper_metadata
from larklab.utils.identifiers import split_doi_or_url


@click.command("db-add")
@click.argument("url_or_doi")
@click.option("--title", default=None, help="Override paper title")
@click.option(
    "--authors",
    default=None,
    help="Override authors (pipe-separated, e.g. 'A|B')",
)
@click.option("--journal", default=None, help="Override journal name")
@click.option("--abstract", default=None, help="Override paper abstract")
def add_paper(url_or_doi, title, authors, journal, abstract):
    """Add a paper by URL or DOI"""
    config = load_config()
    doi, url = split_doi_or_url(url_or_doi)

    click.echo(f"Fetching paper (DOI: {doi or 'unknown'})...")
    paper = fetch_paper_metadata(doi, url)
    apply_overrides(
        paper, title=title, authors=authors, journal=journal, abstract=abstract
    )

    if not paper.title:
        raise click.ClickException(
            "Could not extract paper title. Use --title to provide it manually."
        )
    if not paper.doi:
        raise click.ClickException(
            "Could not determine a DOI for this paper (a DOI is required). "
            "Pass the DOI instead of a URL."
        )

    print_paper_preview(paper)
    missing = paper.missing_metadata()  # the title was checked above
    if missing:
        click.echo(f"\n  Missing: {', '.join(missing)}")
    click.echo()
    if not click.confirm("Proceed?", default=not missing):
        click.echo("Cancelled.")
        return

    click.echo("Generating embedding...")
    paper.embedding = embed_paper(paper)

    with PaperRepository(config.db_path) as repository:
        if _resolve_duplicates(repository, paper):
            with reject_duplicate_titles():
                paper_id = repository.add(paper)
            click.echo(f"Saved (id={paper_id}).")


def _resolve_duplicates(repository: PaperRepository, paper: Paper) -> bool:
    """Ask what to do about each similar paper already stored.

    Returns True if `paper` should still be added as a new entry; False if it
    replaced an existing entry or the user cancelled.
    """
    matches = repository.find_duplicates(paper)
    for number, (existing, score) in enumerate(matches, 1):
        click.echo(
            f"\nSimilar paper ({number}/{len(matches)}, similarity: {score:.3f}):"
        )
        print_paper_entry(existing)
        choice = click.prompt(
            "Action",
            type=click.Choice(["update", "new", "skip"]),
            default="new",
            prompt_suffix=(
                "\n  update = this is the same paper, overwrite"
                "\n  new    = different paper, check next"
                "\n  skip   = cancel\n> "
            ),
        )
        if choice == "update":
            with reject_duplicate_titles():
                repository.update(existing.id, paper)
            click.echo(f"Updated paper (id={existing.id}).")
            return False
        if choice == "skip":
            click.echo("Skipped.")
            return False
    return True
