"""Fixtures for the command tests: a temp library, with Ollama stubbed out."""

import importlib

import pytest
from click.testing import CliRunner

_LIBRARY_COMMAND_MODULES = ("add", "edit", "browse", "health", "backup")
_MODULES = {
    name: importlib.import_module(f"larklab.cli.library.{name}")
    for name in _LIBRARY_COMMAND_MODULES
}


@pytest.fixture
def run(config, monkeypatch, one_hot):
    """Invoke a library command against the temp library; `embed_*` are stubbed."""
    for module in _MODULES.values():
        monkeypatch.setattr(module, "load_config", lambda: config)
    for name in ("add", "edit"):
        monkeypatch.setattr(_MODULES[name], "embed_paper", lambda paper: one_hot(0))
    for name in ("health", "backup"):
        monkeypatch.setattr(
            _MODULES[name],
            "embed_papers",
            lambda papers: [one_hot(i + 1) for i, _ in enumerate(papers)],
        )

    def invoke(command, args, input=None):
        return CliRunner().invoke(command, args, input=input)

    return invoke
