import math
from types import SimpleNamespace

import pytest

from larklab.library import embedder
from larklab.library.embedder import EMBED_DIM, embed_papers, embed_text


@pytest.fixture
def fake_ollama(monkeypatch):
    """Ollama stand-in: one 4096-dim vector per input text. Records request sizes."""
    request_sizes: list[int] = []

    def embed(model, input):
        texts = [input] if isinstance(input, str) else input
        request_sizes.append(len(texts))
        vector = [3.0, 4.0] + [0.0] * 4094
        return {"embeddings": [vector for _ in texts]}

    monkeypatch.setattr(embedder, "_client", SimpleNamespace(embed=embed))
    return request_sizes


def test_vectors_are_truncated_and_normalised(fake_ollama):
    vector = embed_text("query")

    assert len(vector) == EMBED_DIM
    assert math.sqrt(sum(x * x for x in vector)) == pytest.approx(1.0)
    assert vector[:2] == pytest.approx([0.6, 0.8])


def test_many_papers_are_sent_in_batches(fake_ollama, make_paper):
    papers = [make_paper(f"Paper {i}") for i in range(70)]

    embeddings = embed_papers(papers)

    assert len(embeddings) == 70
    assert fake_ollama == [32, 32, 6]


def test_no_papers_means_no_request(fake_ollama):
    assert embed_papers([]) == []
    assert fake_ollama == []


def test_paper_text_is_title_then_abstract(make_paper):
    paper = make_paper("The Title", abstract="The abstract.")

    assert embedder.paper_embedding_text(paper) == "The Title\nThe abstract."


def test_a_hung_ollama_cannot_block_cron_forever():
    """Regression: the default client has no timeout at all."""
    timeout = embedder._client._client.timeout

    assert timeout.read is not None and timeout.read <= 300
