"""db-export and db-import: move the library in and out as JSON or Markdown."""

import json
import re
from pathlib import Path

import click

from larklab.config import DATA_DIR, load_config
from larklab.library.embedder import embed_papers
from larklab.library.repository import PaperRepository
from larklab.models import Paper
from larklab.sources.papers.metadata_lookup import fetch_paper_metadata
from larklab.utils.files import write_text_atomically
from larklab.utils.http import build_http_client

_JSONS_DIR = DATA_DIR / "jsons"
_MARKDOWN_PATH = DATA_DIR / "papers.md"

# `- [Title](URL)` (the URL may be empty), then optionally `  - DOI: ...`
_MARKDOWN_ENTRY = re.compile(
    r"^- \[(.+?)\]\((.*?)\)[ \t\r]*(?:\n[ \t]+-[ \t]+DOI:[ \t]*(.+))?$", re.MULTILINE
)


@click.command("db-export")
@click.option(
    "--output",
    default=None,
    type=click.Path(),
    help="Output path (default: data/jsons/)",
)
@click.option(
    "--query",
    default=None,
    help="Export only papers matching keyword in title",
)
@click.option(
    "--md",
    is_flag=True,
    help="Export as Markdown (default: data/papers.md)",
)
def export_papers(output, query, md):
    """Export papers to individual JSONs or Markdown"""
    config = load_config()
    with PaperRepository(config.db_path) as repository:
        papers = repository.list_papers()
    if query:
        papers = [p for p in papers if query.lower() in p.title.lower()]

    if md:
        path = Path(output) if output else _MARKDOWN_PATH
        _write_markdown(papers, path)
        click.echo(f"Exported {len(papers)} papers to {path}")
    else:
        directory = Path(output) if output else _JSONS_DIR
        _write_json_files(papers, directory)
        click.echo(f"Exported {len(papers)} papers to {directory}/")


@click.command("db-import")
@click.option(
    "--input",
    "input_path",
    default=None,
    type=click.Path(exists=True),
    help="Input path: directory of JSONs, single JSON, or Markdown file",
)
@click.option(
    "--md",
    is_flag=True,
    help="Import from Markdown (default: data/papers.md)",
)
@click.option("--yes", "-y", is_flag=True, help="Replace the library without asking")
def import_papers(input_path, md, yes):
    """Import papers from JSONs or Markdown (replaces all existing data)"""
    config = load_config()
    if not _confirm_replace_library(config.db_path, assume_yes=yes):
        click.echo("Cancelled.")
        return

    if md:
        papers = _read_markdown(Path(input_path) if input_path else _MARKDOWN_PATH)
    else:
        papers = _read_json(Path(input_path) if input_path else _JSONS_DIR)

    click.echo(f"Generating embeddings for {len(papers)} papers...")
    for paper, embedding in zip(papers, embed_papers(papers), strict=True):
        paper.embedding = embedding

    with PaperRepository(config.db_path) as repository:
        stored = repository.replace_all(papers)
    click.echo(f"Imported {stored} papers.")


def parse_papers_markdown(text: str) -> list[tuple[str, str, str | None]]:
    """Parse papers.md into (title, url, doi) entries; `(none)` means no DOI."""
    return [
        (title, url, None if doi.strip() in ("", "(none)") else doi.strip())
        for title, url, doi in _MARKDOWN_ENTRY.findall(text)
    ]


def _confirm_replace_library(db_path: str, *, assume_yes: bool) -> bool:
    with PaperRepository(db_path) as repository:
        existing = repository.count()
    if existing == 0 or assume_yes:
        return True
    return click.confirm(
        f"This replaces all {existing} papers in the library. Continue?",
        default=False,
    )


def _write_markdown(papers: list[Paper], path: Path) -> None:
    lines = [f"# Reference Papers ({len(papers)})\n"]
    for paper in papers:
        url = paper.url if paper.doi else ""
        lines.append(f"- [{paper.title}]({url})")
        lines.append(f"  - DOI: {paper.doi or '(none)'}")
        lines.append("")
    write_text_atomically(path, "\n".join(lines))


def _write_json_files(papers: list[Paper], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() == _JSONS_DIR.resolve():
        for stale_file in directory.glob("*.json"):
            stale_file.unlink()
    for paper in papers:
        write_text_atomically(
            directory / f"{paper.id}.json",
            json.dumps(_paper_to_dict(paper), indent=2, ensure_ascii=False),
        )


def _paper_to_dict(paper: Paper) -> dict:
    return {
        "title": paper.title,
        "authors": paper.authors,
        "journal": paper.journal,
        "abstract": paper.abstract,
        "doi": paper.doi,
    }


def _read_json(path: Path) -> list[Paper]:
    """Read a directory of `<id>.json` files, a JSON file, or a list of papers."""
    if path.is_dir():
        files = sorted(
            (f for f in path.glob("*.json") if f.stem.isdigit()),
            key=lambda f: int(f.stem),
        )
        items = [json.loads(f.read_text()) for f in files]
    elif path.is_file():
        raw = json.loads(path.read_text())
        items = raw if isinstance(raw, list) else [raw]
    else:
        raise click.ClickException(f"Not found: {path}")

    click.echo(f"Read {len(items)} papers from {path}")
    return [
        Paper(
            title=item["title"],
            authors=item["authors"],
            journal=item["journal"],
            abstract=item["abstract"],
            doi=item.get("doi", ""),
        )
        for item in items
    ]


def _read_markdown(path: Path) -> list[Paper]:
    """Read papers.md and re-fetch each paper's metadata via its DOI/URL."""
    if not path.exists():
        raise click.ClickException(f"Not found: {path}")

    entries = parse_papers_markdown(path.read_text())
    click.echo(f"Read {len(entries)} papers from {path}")

    papers = []
    with build_http_client() as client:
        for number, (title, url, doi) in enumerate(entries, 1):
            click.echo(f"  Fetching {number}/{len(entries)}: {title[:50]}...")
            try:
                paper = fetch_paper_metadata(doi or "", url or "", client=client)
            except Exception as error:  # one bad page must not lose the whole import
                click.echo(
                    f"    fetch failed ({error}); keeping the title only", err=True
                )
                paper = Paper.empty(doi or "")
            paper.title = paper.title or title
            paper.doi = paper.doi or doi or ""
            papers.append(paper)
    return papers
