"""`digest` is what cron runs daily: cover its delivery and cleanup rules.

Every Slack call here is faked; nothing is ever posted.
"""

import importlib
import json
from datetime import UTC, datetime

import pytest
from builders import scholar_paper
from click.testing import CliRunner

from larklab.models import ScholarPaper

# The module, not the command of the same name that `larklab.cli` re-exports
digest_cli = importlib.import_module("larklab.cli.digest")


def _paper(title: str, email_id: str = "m1", day: int = 16) -> ScholarPaper:
    return scholar_paper(
        title,
        abstract="snippet",
        url=f"https://doi.org/10.1000/{title.lower()}",
        source_email_id=email_id,
        received_at=datetime(2026, 11, day, 8, tzinfo=UTC),
        doi=f"10.1000/{title.lower()}",
    )


class FakeGmail:
    """Stands in for GmailClient; remembers which message ids were trashed."""

    last_instance = None
    papers = None  # set per test: what parse_emails returns

    def __init__(self, config):
        self.trashed_ids = None
        FakeGmail.last_instance = self

    def list_message_ids(self, query, max_results, days_back):
        return ["m1", "m2"]

    def fetch_message_timestamps(self, message_ids):
        return [("m1", 0), ("m2", 1)]

    def fetch_full_messages(self, message_ids):
        return [{"id": message_id} for message_id in message_ids]

    def parse_emails(self, raw_messages):
        return self.papers or [_paper("Alpha", "m1"), _paper("Beta", "m2")]

    def trash_messages(self, message_ids, verbose=False):
        self.trashed_ids = list(message_ids)
        return list(message_ids)


@pytest.fixture
def invoke(config, monkeypatch):
    FakeGmail.papers = None
    monkeypatch.setattr(digest_cli, "load_config", lambda: config)
    monkeypatch.setattr(digest_cli, "GmailClient", FakeGmail)

    def run(*args):
        return CliRunner().invoke(
            digest_cli.digest, ["--no-fetch-abstracts", *args], catch_exceptions=False
        )

    return run


def test_print_only_run_with_cleanup_trashes_the_emails_it_printed(invoke):
    result = invoke("--no-slack", "--cleanup")

    assert "Google Scholar Digest — 2 papers" in result.output
    assert "Trashed 2 processed emails." in result.output
    assert FakeGmail.last_instance.trashed_ids == ["m1", "m2"]


def test_emails_are_never_trashed_unless_cleanup_is_asked_for(invoke, monkeypatch):
    monkeypatch.setattr(
        digest_cli, "send_digest_to_slack", lambda digests, **kw: digests
    )

    for options in (["--no-slack"], []):  # printed, or delivered to Slack
        result = invoke(*options)

        assert "Trashed" not in result.output
        assert FakeGmail.last_instance.trashed_ids is None


def test_emails_are_kept_when_slack_delivery_fails(invoke, monkeypatch):
    monkeypatch.setattr(digest_cli, "send_digest_to_slack", lambda *a, **k: [])

    result = invoke("--cleanup")

    assert "Slack delivery failed" in result.output
    assert FakeGmail.last_instance.trashed_ids is None


def test_the_channel_option_reaches_slack_and_delivery_allows_cleanup(
    invoke, monkeypatch
):
    delivered = []

    def send(digests, *, token, channel):
        delivered.append(channel)
        return digests

    monkeypatch.setattr(digest_cli, "send_digest_to_slack", send)

    result = invoke("--channel", "reading-group", "--cleanup")

    assert delivered == ["reading-group"]
    assert FakeGmail.last_instance.trashed_ids == ["m1", "m2"]
    assert "Trashed 2 processed emails." in result.output


def test_an_email_that_held_no_paper_is_never_trashed(invoke):
    """m2 parsed to nothing: it may be a new alert layout, so it stays in the inbox."""
    FakeGmail.papers = [_paper("Alpha", "m1")]

    invoke("--no-slack", "--cleanup")

    assert FakeGmail.last_instance.trashed_ids == ["m1"]


def test_an_email_whose_papers_were_all_repeats_is_trashed_too(invoke):
    """m2 only repeats m1's paper: it must not stay in the inbox to be re-read."""
    FakeGmail.papers = [_paper("Alpha", "m1"), _paper("alpha", "m2")]

    invoke("--no-slack", "--cleanup")

    assert FakeGmail.last_instance.trashed_ids == ["m1", "m2"]


def test_emails_of_digests_that_did_not_reach_slack_are_kept(invoke, monkeypatch):
    FakeGmail.papers = [_paper("Newer", "m1", day=16), _paper("Older", "m2", day=10)]
    monkeypatch.setattr(
        digest_cli, "send_digest_to_slack", lambda digests, **kw: digests[:1]
    )

    result = invoke("--cleanup")

    assert FakeGmail.last_instance.trashed_ids == ["m1"]  # m2's digest never went out
    assert "Trashed 1 processed emails." in result.output
    assert "1 digest(s) were not delivered in full" in result.output


def test_output_json_has_the_fields_downstream_scripts_expect(invoke, tmp_path):
    target = tmp_path / "digest.json"

    invoke("--no-slack", "--output-json", str(target))

    data = json.loads(target.read_text())
    assert set(data) == {"generated_at", "num_emails", "num_parsed", "digests"}
    assert (data["num_emails"], data["num_parsed"]) == (2, 2)
    [day] = data["digests"]
    first = day["papers"][0]
    assert set(first) == {
        "title",
        "authors",
        "journal",
        "abstract",
        "url",
        "received_at",
        "summary",
        "doi",
        "similar_papers",
    }
    assert first["received_at"].startswith("2026-11-16")


def test_nothing_is_sent_when_there_are_no_emails(config, monkeypatch):
    class EmptyGmail(FakeGmail):
        def list_message_ids(self, *args):
            return []

    monkeypatch.setattr(digest_cli, "load_config", lambda: config)
    monkeypatch.setattr(digest_cli, "GmailClient", EmptyGmail)

    result = CliRunner().invoke(digest_cli.digest, ["--no-slack"])

    assert "No papers found. Nothing to send." in result.output
    assert EmptyGmail.last_instance.trashed_ids is None
