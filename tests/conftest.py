"""Shared fixtures. Everything here is offline: no network, no Ollama."""

import time

import httpx
import pytest

from larklab.config import Config
from larklab.library.embedder import EMBED_DIM
from larklab.library.repository import PaperRepository
from larklab.models import Paper


@pytest.fixture(autouse=True)
def sleeps(monkeypatch) -> list[float]:
    """No test ever really waits. The pauses a test provoked, in order, are in the
    returned list: ask for `sleeps` to assert on them."""
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)
    return waits


@pytest.fixture
def one_hot():
    """Unit vectors along one axis: identical axes → distance 0, others → 1."""

    def build(axis: int) -> list[float]:
        vector = [0.0] * EMBED_DIM
        vector[axis] = 1.0
        return vector

    return build


@pytest.fixture
def make_paper():
    def build(title: str = "A Paper", **overrides) -> Paper:
        slug = "".join(c if c.isalnum() else "-" for c in title.lower())
        fields = {
            "title": title,
            "authors": ["Doe, Jane"],
            "journal": "Nature",
            "abstract": "An abstract.",
            "doi": f"10.1000/{slug}",
        }
        return Paper(**{**fields, **overrides})

    return build


@pytest.fixture
def repository(tmp_path):
    with PaperRepository(str(tmp_path / "library.db")) as repo:
        yield repo


@pytest.fixture
def config(tmp_path):
    """A Config whose DB lives in the test's temp directory."""
    return Config(
        credentials_path=str(tmp_path / "credentials.json"),
        token_path=str(tmp_path / "token.json"),
        slack_bot_token="",
        db_path=str(tmp_path / "library.db"),
    )


@pytest.fixture
def http_client():
    """Build a client whose responses come from a handler: `http_client(handler)`."""
    clients = []

    def build(handler) -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.close()
