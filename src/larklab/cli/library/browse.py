"""db-list and db-search: look at what is in the library."""

import click

from larklab.config import load_config
from larklab.library.embedder import embed_text
from larklab.library.repository import PaperRepository
from larklab.models import Paper
from larklab.outputs.terminal import print_paper_entry

_SEARCH_LIMIT = 5
_SEARCH_LIMIT_WHEN_FILTERING = 20  # over-fetch so the journal filter has candidates


@click.command("db-list")
def list_papers():
    """List papers in the database"""
    config = load_config()
    with PaperRepository(config.db_path) as repository:
        papers = repository.list_papers()

    if not papers:
        click.echo("No papers found.")
        return

    click.echo(f"=== papers ({len(papers)}) ===\n")
    for paper in papers:
        print_paper_entry(paper)


@click.command("db-search")
@click.argument("query", required=False, default=None)
@click.option("--journal", default=None, help="Filter by journal name")
def search_paper(query, journal):
    """Search papers in DB by keyword, journal, or similarity"""
    if not query and not journal:
        raise click.UsageError("Provide a query or --journal to search.")

    config = load_config()
    journal_filter = journal.lower() if journal else None
    with PaperRepository(config.db_path) as repository:
        papers = repository.list_papers()
        if journal_filter:
            papers = [p for p in papers if journal_filter in p.journal.lower()]
        keyword_matches = (
            [p for p in papers if query.lower() in p.title.lower()] if query else papers
        )
        similar = _search_similar(repository, query, journal_filter) if query else []

    if keyword_matches:
        click.echo(f"=== keyword matches ({len(keyword_matches)}) ===\n")
        for paper in keyword_matches:
            print_paper_entry(paper, show_abstract=True)

    if similar:
        click.echo(f"=== similar papers (top {len(similar)}) ===\n")
        for paper, distance in similar:
            print_paper_entry(paper, similarity=1 - distance)

    if not keyword_matches and not similar:
        click.echo("No matches found.")


def _search_similar(
    repository: PaperRepository, query: str, journal_filter: str | None
) -> list[tuple[Paper, float]]:
    limit = _SEARCH_LIMIT_WHEN_FILTERING if journal_filter else _SEARCH_LIMIT
    results = repository.search_similar(embed_text(query), limit=limit)
    if journal_filter:
        results = [(p, d) for p, d in results if journal_filter in p.journal.lower()]
    return results[:_SEARCH_LIMIT]
