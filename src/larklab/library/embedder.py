"""Ollama embeddings for papers (qwen3-embedding, Matryoshka-truncated)."""

import logging
import math
import time
from collections.abc import Sequence
from itertools import batched

import httpx

from larklab.library.repository import EMBED_DIM
from larklab.models import Paper, ScholarPaper

logger = logging.getLogger(__name__)

EMBED_MODEL = "qwen3-embedding:8b"
_BATCH_SIZE = 32  # texts per Ollama request; bounds memory for large crawls
_TIMEOUT_SECONDS = 120  # the default client waits forever
_ATTEMPTS = 3  # per request: one slow moment must not lose an hour of embedding
_LOG_EVERY_BATCHES = 10  # a long run says how far it has got
_client = None  # built on first use: importing ollama costs a quarter of a second


def _ollama_client():
    global _client
    if _client is None:
        import ollama  # lazy, so commands that never embed start faster

        _client = ollama.Client(timeout=_TIMEOUT_SECONDS)
    return _client


def paper_embedding_text(paper: Paper | ScholarPaper) -> str:
    return f"{paper.title}\n{paper.abstract}"


def embed_text(text: str) -> list[float]:
    """Embed arbitrary text (e.g. a search query)."""
    response = _ollama_client().embed(model=EMBED_MODEL, input=text)
    return _truncate_and_normalize(response["embeddings"][0])


def embed_paper(paper: Paper | ScholarPaper) -> list[float]:
    return embed_text(paper_embedding_text(paper))


def embed_papers(papers: Sequence[Paper | ScholarPaper]) -> list[list[float]]:
    """Embed many papers, sending them to Ollama in batches."""
    embeddings: list[list[float]] = []
    for number, batch in enumerate(batched(papers, _BATCH_SIZE), 1):
        response = _embed_with_retry([paper_embedding_text(p) for p in batch])
        embeddings.extend(_truncate_and_normalize(v) for v in response["embeddings"])
        if number % _LOG_EVERY_BATCHES == 0:
            logger.info("  Embedded %d/%d papers...", len(embeddings), len(papers))
    return embeddings


def _embed_with_retry(texts: list[str]):
    import ollama  # lazy, see _ollama_client

    for attempt in range(1, _ATTEMPTS + 1):
        try:
            return _ollama_client().embed(model=EMBED_MODEL, input=texts)
        except (ollama.ResponseError, ConnectionError, httpx.TransportError) as error:
            if attempt == _ATTEMPTS:
                raise
            logger.warning(
                "Embedding request failed (attempt %d/%d): %s",
                attempt,
                _ATTEMPTS,
                error,
            )
            time.sleep(5 * attempt)


def _truncate_and_normalize(vector: list[float]) -> list[float]:
    """Slice to EMBED_DIM and L2-normalize (Matryoshka)."""
    truncated = vector[:EMBED_DIM]
    norm = math.sqrt(sum(x * x for x in truncated))
    return [x / norm for x in truncated] if norm > 0 else truncated
