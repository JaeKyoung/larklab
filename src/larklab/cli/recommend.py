"""CLI command for paper recommendations."""

from collections import defaultdict

import click

from larklab.cli.common import CONTEXT_SETTINGS
from larklab.config import load_config
from larklab.database.embedder import embed_papers
from larklab.database.repository import PaperRepository
from larklab.extract.crawler import (
    ARXIV_DEFAULTS,
    BIORXIV_DEFAULTS,
    crawl_arxiv,
    crawl_biorxiv,
)
from larklab.load.slack_recommend import send_recommendations_to_slack


@click.command("recommend", context_settings=CONTEXT_SETTINGS)
@click.argument(
    "source",
    required=False,
    default=None,
    type=click.Choice(["arxiv", "biorxiv"]),
)
@click.option(
    "--categories",
    "-c",
    default=None,
    help="Comma-separated categories (requires source)",
)
@click.option(
    "--days-back", "-d", default=1, help="Days to look back", show_default=True
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
@click.option("--no-slack", is_flag=True, help="Skip sending to Slack (print only)")
def recommend(source, categories, days_back, top_n, channel, threshold, no_slack):
    """Recommend papers from arXiv or bioRxiv based on your reference library."""
    if categories and not source:
        raise click.UsageError(
            "--categories requires a source argument (arxiv or biorxiv)"
        )

    config = load_config()
    config.slack_channel = channel

    sources = [source] if source else ["arxiv", "biorxiv"]
    cats = [c.strip() for c in categories.split(",")] if categories else None

    all_papers = []
    source_counts = {}

    for src in sources:
        defaults = ARXIV_DEFAULTS if src == "arxiv" else BIORXIV_DEFAULTS
        display = cats or defaults
        print(f"Crawling {src} ({', '.join(display)})...")

        if src == "arxiv":
            papers = crawl_arxiv(cats, days_back)
        else:
            papers = crawl_biorxiv(cats, days_back)

        source_counts[src] = len(papers)
        all_papers.extend(papers)

    if not all_papers:
        print("No papers found.")
        return

    total = sum(source_counts.values())
    parts = [f"{src}: {n}" for src, n in source_counts.items()]
    print(f"Found {total} papers ({', '.join(parts)}).")

    with PaperRepository(config.db_path) as repo:
        refs = repo.get_papers()
        if not refs:
            print("No reference papers in DB. Add papers with `db-add` first.")
            return

        ref_titles = {p.title.lower().strip() for p in refs}
        all_papers = [
            p for p in all_papers if p.title.lower().strip() not in ref_titles
        ]
        if not all_papers:
            print("All crawled papers are already in your reference library.")
            return

        print(f"Embedding {len(all_papers)} papers...")
        embeddings = embed_papers(all_papers)

        scored = []
        for paper, embedding in zip(all_papers, embeddings):
            results = repo.search_similar(embedding, limit=3)
            if results:
                score = 1 - results[0][1]
                similar = [(r.title, 1 - d) for r, d in results]
                scored.append((paper, score, similar))

    # per-date-per-source totals (before scoring)
    date_totals = defaultdict(lambda: defaultdict(int))
    for p in all_papers:
        date_totals[p.published_date][p.journal.lower()] += 1

    if not scored:
        print("No similarity scores found. Run `db-rebuild` to regenerate embeddings.")
        return

    scored.sort(key=lambda x: x[1], reverse=True)
    scored = [s for s in scored if s[1] >= threshold]

    if not scored:
        print(f"No papers above threshold ({threshold:.2f}).")
        return

    scored = scored[:top_n]

    by_date = defaultdict(list)
    for paper, score, similar in scored:
        by_date[paper.published_date].append((paper, score, similar))

    if no_slack:
        _print_recommendations(scored, by_date, date_totals)
    else:
        send_recommendations_to_slack(by_date, config, date_totals)
        _print_recommendations(scored, by_date, date_totals)


def _print_recommendations(scored, by_date, date_totals):
    for pub_date in sorted(by_date, reverse=True):
        label = pub_date.strftime("%Y-%m-%d") if pub_date else "unknown"
        filtered = by_date[pub_date]
        totals = date_totals.get(pub_date, {})
        filtered_counts = defaultdict(int)
        for p, _, _ in filtered:
            filtered_counts[p.journal.lower()] += 1
        parts = [f"  {src}: {filtered_counts[src]}/{totals[src]}" for src in totals]
        print(f"\n--- Paper Recommendations — {label} ---")
        for part in parts:
            print(part)

    show = len(scored)
    print(f"\nTop {show}:\n")
    for i, (paper, score, similar) in enumerate(scored):
        ref_title = similar[0][0]
        authors = ", ".join(paper.authors[:3])
        if len(paper.authors) > 3:
            authors += " et al."
        print(f"{i + 1:3d}. [{score:.2f}] {paper.title}")
        print(f"     {authors}")
        print(f"     → {ref_title}")
        print(f"     {paper.url}")
        print()
