"""db-edit and db-delete: change or remove a paper already in the library."""

import click

from larklab.cli.library.field_edits import apply_overrides, reject_duplicate_titles
from larklab.config import load_config
from larklab.library.embedder import embed_paper
from larklab.library.repository import PaperRepository


@click.command("db-edit")
@click.argument("paper_id", type=int)
@click.option("--title", default=None, help="New title")
@click.option(
    "--authors",
    default=None,
    help="New authors (pipe-separated, e.g. 'A|B')",
)
@click.option("--journal", default=None, help="New journal name")
@click.option("--abstract", default=None, help="New abstract")
@click.option("--doi", default=None, help="New DOI")
def edit_paper(paper_id, title, authors, journal, abstract, doi):
    """Edit fields of an existing paper"""
    config = load_config()
    with PaperRepository(config.db_path) as repository:
        paper = repository.get_by_id(paper_id)
        if paper is None:
            raise click.ClickException(f"Paper {paper_id} not found.")

        apply_overrides(
            paper,
            title=title,
            authors=authors,
            journal=journal,
            abstract=abstract,
            doi=doi,
        )
        if title or abstract:  # the embedding is built from title + abstract
            paper.embedding = embed_paper(paper)
        with reject_duplicate_titles():
            repository.update(paper_id, paper)
    click.echo(f"Updated paper (id={paper_id}).")


@click.command("db-delete")
@click.argument("paper_id", type=int)
def delete_paper(paper_id):
    """Delete a paper from the database"""
    config = load_config()
    with PaperRepository(config.db_path) as repository:
        paper = repository.get_by_id(paper_id)
        if paper is None:
            raise click.ClickException(f"Paper {paper_id} not found.")

        click.echo(f"  [{paper.id}] {paper.title}")
        if not click.confirm("Delete this paper?", default=False):
            click.echo("Cancelled.")
            return
        repository.delete(paper_id)
    click.echo(f"Deleted paper (id={paper_id}).")
