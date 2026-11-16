"""Console output for digests, recommendations, and library entries."""

from larklab.models import DailyDigest, Paper, RecommendationResult

_MAX_LISTED_AUTHORS = 3


def format_authors(authors: list[str]) -> str:
    """'A, B, C et al.' — or '(none)' when there are no authors."""
    names = ", ".join(authors[:_MAX_LISTED_AUTHORS])
    if len(authors) > _MAX_LISTED_AUTHORS:
        names += " et al."
    return names or "(none)"


def print_digest(digests: list[DailyDigest]) -> None:
    total = sum(len(digest.papers) for digest in digests)
    print(f"\n{'=' * 60}")
    print(f"  Google Scholar Digest — {total} papers, {len(digests)} days")
    print(f"{'=' * 60}\n")

    for digest in digests:
        print(f"--- {digest.date} ({len(digest.papers)} papers) ---\n")
        for number, paper in enumerate(digest.papers, 1):
            print(f"  {number}. {paper.title}")
            print(f"     Authors: {', '.join(paper.authors) or 'Unknown'}")
            if paper.journal:
                print(f"     Journal: {paper.journal}")
            if paper.abstract:
                print(f"     Abstract: {paper.abstract}")
            print(f"     URL: {paper.url}")
            for rank, (title, score) in enumerate(paper.similar_papers or [], 1):
                print(f"     Top {rank} related paper (similarity: {score:.3f})")
                print(f"     {title}")
            print()


def print_recommendations(result: RecommendationResult) -> None:
    for published in result.by_date():
        label = published.isoformat() if published else "unknown"
        print(f"\n--- Paper Recommendations — {label} ---")
        for source, kept, total in result.source_counts(published):
            print(f"  {source}: {kept}/{total}")

    print(f"\nTop {len(result.recommendations)}:\n")
    for number, recommendation in enumerate(result.recommendations, 1):
        paper = recommendation.paper
        closest_reference = recommendation.similar_papers[0][0]
        print(f"{number:3d}. [{recommendation.score:.2f}] {paper.title}")
        print(f"     {format_authors(paper.authors)}")
        print(f"     → {closest_reference}")
        print(f"     {paper.url}")
        print()


def print_paper_preview(paper: Paper) -> None:
    """Show what `db-add` fetched, before the user confirms."""
    print(f"\n  Title:    {paper.title}")
    print(f"  Authors:  {format_authors(paper.authors)}")
    print(f"  Journal:  {paper.journal or '(none)'}")
    print(f"  Abstract: {paper.abstract or '(none)'}")


def print_paper_entry(
    paper: Paper,
    *,
    similarity: float | None = None,
    show_abstract: bool = False,
) -> None:
    """One library entry, as listed by db-list / db-search."""
    if similarity is None:
        print(f"[{paper.id}] {paper.title}")
    else:
        print(f"[{paper.id}] similarity: {similarity:.3f}")
        print(f"    {paper.title}")
    print(f"    {format_authors(paper.authors)} — {paper.journal}")
    print(f"    {paper.url}")
    if show_abstract:
        print(f"    {paper.abstract}")
    print()
