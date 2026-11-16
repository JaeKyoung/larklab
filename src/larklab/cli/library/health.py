"""db-check and db-rebuild: find and repair problems in the library."""

import click

from larklab.config import load_config
from larklab.library.embedder import embed_papers
from larklab.library.repository import PaperRepository
from larklab.models import Paper
from larklab.sources.papers.metadata_lookup import fetch_paper_metadata
from larklab.utils.http import build_http_client

_ABSTRACT_PREVIEW_CHARS = 80


@click.command("db-check")
@click.option(
    "--refetch",
    is_flag=True,
    help="Re-fetch from URL/DOI and compare with DB",
)
def check_papers(refetch):
    """Check all papers for missing or outdated fields"""
    config = load_config()
    with PaperRepository(config.db_path) as repository:
        papers = repository.list_papers()
        ids_without_embedding = set(repository.ids_without_embedding())

    refetched = _refetch_papers(papers) if refetch else {}

    issue_count = 0
    for paper in papers:
        problems = _missing_field_problems(paper)
        if paper.id in ids_without_embedding:
            problems.append("missing: embedding (run db-rebuild)")
        changes = (
            _field_changes(paper, refetched[paper.id]) if paper.id in refetched else []
        )

        if not problems and not changes:
            continue
        issue_count += 1
        click.echo(f"[{paper.id}] {paper.title or '(no title)'}")
        for problem in problems:
            click.echo(f"    {problem}")
        for field, stored_value, fetched_value in changes:
            click.echo(f"    changed: {field}")
            click.echo(f"      DB:      {stored_value}")
            click.echo(f"      Fetched: {fetched_value}")
        click.echo()

    if issue_count == 0:
        click.echo(f"All {len(papers)} papers OK.")
    else:
        click.echo(f"{issue_count} issue(s) found.")


@click.command("db-rebuild")
def rebuild_embeddings():
    """Re-generate all embeddings from stored title + abstract"""
    config = load_config()
    with PaperRepository(config.db_path) as repository:
        papers = repository.list_papers()
        click.echo(f"Embedding {len(papers)} papers...")
        # Embed everything before touching the DB: a failure here changes nothing.
        embeddings = embed_papers(papers)
        repository.replace_all_embeddings(
            {
                paper.id: embedding
                for paper, embedding in zip(papers, embeddings, strict=True)
            }
        )
    click.echo(f"Rebuilt embeddings for {len(papers)} papers.")


def _missing_field_problems(paper: Paper) -> list[str]:
    return [f"missing: {name}" for name in paper.missing_metadata()]


def _refetch_papers(papers: list[Paper]) -> dict[int, Paper]:
    click.echo(f"Re-fetching {len(papers)} papers...")
    refetched: dict[int, Paper] = {}
    with build_http_client() as client:
        for paper in papers:
            try:
                refetched[paper.id] = fetch_paper_metadata(paper.doi, client=client)
            except Exception as error:
                click.echo(f"  [{paper.id}] re-fetch failed: {error}", err=True)
    return refetched


def _field_changes(stored: Paper, fetched: Paper) -> list[tuple[str, str, str]]:
    """(field, stored, fetched) where the fetched value is non-empty and differs."""
    changes = []
    for name in ("title", "journal", "abstract"):
        stored_value, fetched_value = getattr(stored, name), getattr(fetched, name)
        if fetched_value and fetched_value != stored_value:
            if name == "abstract":  # abstracts are long; titles must stay readable
                stored_value, fetched_value = (
                    _shorten(stored_value),
                    _shorten(fetched_value),
                )
            changes.append((name, stored_value or "(none)", fetched_value))
    if fetched.authors and fetched.authors != stored.authors:
        changes.append(
            (
                "authors",
                ", ".join(stored.authors) or "(none)",
                ", ".join(fetched.authors),
            )
        )
    return changes


def _shorten(text: str) -> str:
    if len(text) <= _ABSTRACT_PREVIEW_CHARS:
        return text
    return text[:_ABSTRACT_PREVIEW_CHARS] + "..."
