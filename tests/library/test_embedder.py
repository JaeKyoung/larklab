import math
from types import SimpleNamespace

import httpx
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


def test_a_hung_ollama_cannot_block_cron_forever(monkeypatch):
    """Regression: the default client has no timeout at all."""
    monkeypatch.setattr(embedder, "_client", None)  # as at start-up: not built yet
    timeout = embedder._ollama_client()._client.timeout

    assert timeout.read is not None and timeout.read <= 300


def _flaky_ollama(monkeypatch, failures, error=None):
    """Ollama stand-in whose first `failures` requests fail."""
    calls = []

    def embed(model, input):
        calls.append(len(input))
        if len(calls) <= failures:
            raise error or httpx.ReadTimeout("took too long")
        return {"embeddings": [[3.0, 4.0] + [0.0] * 4094 for _ in input]}

    monkeypatch.setattr(embedder, "_client", SimpleNamespace(embed=embed))
    return calls


def test_a_slow_request_is_retried_instead_of_losing_the_whole_run(
    monkeypatch, make_paper, sleeps
):
    calls = _flaky_ollama(monkeypatch, failures=2)

    embeddings = embed_papers([make_paper("One")])

    assert len(embeddings) == 1
    assert calls == [1, 1, 1]  # two failures, then the answer
    assert sleeps == [5, 10]  # a growing pause between attempts


def test_a_request_that_keeps_failing_is_given_up_on(monkeypatch, make_paper):
    calls = _flaky_ollama(monkeypatch, failures=99)

    with pytest.raises(httpx.ReadTimeout):
        embed_papers([make_paper("One")])

    assert len(calls) == embedder._ATTEMPTS


def test_a_long_run_logs_how_far_it_has_got(fake_ollama, make_paper, caplog):
    papers = [make_paper(f"Paper {i}") for i in range(32 * 10 + 5)]

    with caplog.at_level("INFO", logger="larklab.library.embedder"):
        embed_papers(papers)

    assert caplog.messages == ["  Embedded 320/325 papers..."]  # after the 10th batch
