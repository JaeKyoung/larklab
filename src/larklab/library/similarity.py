"""Score papers against the reference library."""

from collections.abc import Sequence

from larklab.library.embedder import embed_papers
from larklab.library.repository import PaperRepository
from larklab.models import Paper, ScholarPaper, SimilarPapers

_TOP_K = 3


def find_similar_references(
    papers: Sequence[Paper | ScholarPaper], repository: PaperRepository
) -> list[SimilarPapers]:
    """For each paper, its closest reference papers as (title, similarity).

    The result is aligned with `papers`; an empty library gives empty lists.
    """
    return [
        [
            (reference.title, 1 - distance)
            for reference, distance in repository.search_similar(
                embedding, limit=_TOP_K
            )
        ]
        for embedding in embed_papers(papers)
    ]
