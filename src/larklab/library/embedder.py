"""Ollama embeddings for papers (qwen3-embedding, Matryoshka-truncated)."""

import math
from collections.abc import Sequence
from itertools import batched

import ollama

from larklab.models import Paper, ScholarPaper

EMBED_MODEL = "qwen3-embedding:8b"
EMBED_DIM = 1024  # Matryoshka truncation of the model's native 4096 dimensions
_BATCH_SIZE = 32  # texts per Ollama request; bounds memory for large crawls
_TIMEOUT_SECONDS = 120  # the default client waits forever
_client = ollama.Client(timeout=_TIMEOUT_SECONDS)


def paper_embedding_text(paper: Paper | ScholarPaper) -> str:
    return f"{paper.title}\n{paper.abstract}"


def embed_text(text: str) -> list[float]:
    """Embed arbitrary text (e.g. a search query)."""
    response = _client.embed(model=EMBED_MODEL, input=text)
    return _truncate_and_normalize(response["embeddings"][0])


def embed_paper(paper: Paper | ScholarPaper) -> list[float]:
    return embed_text(paper_embedding_text(paper))


def embed_papers(papers: Sequence[Paper | ScholarPaper]) -> list[list[float]]:
    """Embed many papers, sending them to Ollama in batches."""
    embeddings: list[list[float]] = []
    for batch in batched(papers, _BATCH_SIZE):
        response = _client.embed(
            model=EMBED_MODEL, input=[paper_embedding_text(p) for p in batch]
        )
        embeddings.extend(_truncate_and_normalize(v) for v in response["embeddings"])
    return embeddings


def _truncate_and_normalize(vector: list[float]) -> list[float]:
    """Slice to EMBED_DIM and L2-normalize (Matryoshka)."""
    truncated = vector[:EMBED_DIM]
    norm = math.sqrt(sum(x * x for x in truncated))
    return [x / norm for x in truncated] if norm > 0 else truncated
