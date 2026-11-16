"""The summarizer against a fake Ollama client: no model is ever loaded."""

from datetime import UTC, datetime

import pytest

from larklab.models import ScholarPaper
from larklab.processing import summarizer


class FakeOllama:
    def __init__(self, content="• one\n• two\n• three", error=None):
        self.calls = []
        self._content, self._error = content, error

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return {"message": {"content": self._content}}


@pytest.fixture
def ollama_client(monkeypatch):
    def install(**kwargs) -> FakeOllama:
        client = FakeOllama(**kwargs)
        monkeypatch.setattr(summarizer, "_client", client)
        return client

    return install


def _paper(abstract: str = "We fold proteins.") -> ScholarPaper:
    return ScholarPaper(
        title="Folding",
        authors=[],
        journal="",
        abstract=abstract,
        url="https://example.com/folding",
        source_email_id="m1",
        received_at=datetime(2026, 11, 16, tzinfo=UTC),
    )


def test_a_paper_without_an_abstract_is_not_sent_to_the_model(ollama_client):
    client = ollama_client()

    assert summarizer.summarize_abstract(_paper(abstract="")) == ""
    assert client.calls == []


def test_the_model_sees_the_title_and_the_abstract(ollama_client):
    client = ollama_client()

    summarizer.summarize_abstract(_paper())

    prompt = client.calls[0]["messages"][0]["content"]
    assert "Title: Folding" in prompt and "Abstract: We fold proteins." in prompt


def test_thinking_is_off_and_the_answer_is_capped(ollama_client):
    """Thinking made each summary ~6x slower and used up the token budget."""
    client = ollama_client()

    summarizer.summarize_abstract(_paper())

    call = client.calls[0]
    assert call["think"] is False
    assert call["options"] == {"num_predict": 512}


def test_the_requested_model_is_used(ollama_client):
    client = ollama_client()

    summarizer.summarize_abstract(_paper(), model="qwen3:4b")

    assert client.calls[0]["model"] == "qwen3:4b"


def test_the_summary_is_trimmed(ollama_client):
    ollama_client(content="\n  • one\n• two  \n")

    assert summarizer.summarize_abstract(_paper()) == "• one\n• two"


def test_a_model_error_reaches_the_caller(ollama_client):
    """The pipeline decides what a failed summary means; nothing is hidden here."""
    ollama_client(error=ConnectionError("ollama is not running"))

    with pytest.raises(ConnectionError):
        summarizer.summarize_abstract(_paper())
