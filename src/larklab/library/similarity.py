"""Score papers against the reference library."""

import logging
import time
from collections.abc import Sequence

from larklab.library.embedder import embed_papers
from larklab.library.repository import PaperRepository
from larklab.models import Paper, ScholarPaper, SimilarPapers

logger = logging.getLogger(__name__)

_TOP_K = 3


def find_similar_references(
    papers: Sequence[Paper | ScholarPaper], repository: PaperRepository
) -> list[SimilarPapers]:
    """For each paper, its closest reference papers as (title, similarity).

    The result is aligned with `papers`; an empty library gives empty lists. The log
    says how long embedding and searching each took: embedding is what a long run
    spends its time on.
    """
    started = time.monotonic()
    embeddings = embed_papers(papers)
    embedded = time.monotonic()
    similar = [
        [
            (reference.title, similarity)
            for reference, similarity in repository.search_similar(
                embedding, limit=_TOP_K
            )
        ]
        for embedding in embeddings
    ]
    if embeddings:
        logger.info(
            "Embedded %d papers in %.0fs, searched the library in %.1fs.",
            len(embeddings),
            embedded - started,
            time.monotonic() - embedded,
        )
    return similar
