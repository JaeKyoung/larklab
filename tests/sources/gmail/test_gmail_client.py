"""GmailClient against a fake Gmail resource: no OAuth, no network."""

import logging

import pytest

from larklab.sources.gmail import client as gmail_client
from larklab.sources.gmail.client import GmailClient


class _Call:
    """What `.execute()` is called on in the Gmail client library."""

    def __init__(self, result=None, error=None):
        self._result, self._error = result, error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class FakeMessages:
    def __init__(self, failing_ids=(), unreadable_ids=()):
        self.queries = []
        self.trashed = []
        self._failing_ids = set(failing_ids)
        self._unreadable_ids = set(unreadable_ids)

    def list(self, userId, q, maxResults):
        self.queries.append((q, maxResults))
        return _Call({"messages": [{"id": "m1"}, {"id": "m2"}]})

    def get(self, userId, id, format, metadataHeaders=None):
        if id in self._unreadable_ids:
            return _Call(error=RuntimeError("gmail cannot read this one"))
        message = {
            "id": id,
            "format": format,
            "internalDate": "1700000000000",
            "payload": {"headers": [{"name": "Subject", "value": f"Alert {id}"}]},
        }
        return _Call(message)

    def trash(self, userId, id):
        if id in self._failing_ids:
            return _Call(error=RuntimeError("gmail said no"))
        self.trashed.append(id)
        return _Call({})


class FakeBatch:
    """Gmail's batch request: runs what was added in one go, reporting each result
    (or error) to the callback, like the real client library."""

    def __init__(self, callback, sizes):
        self._callback, self._sizes, self._added = callback, sizes, []

    def add(self, request, request_id):
        self._added.append((request_id, request))

    def execute(self):
        self._sizes.append(len(self._added))
        for request_id, request in self._added:
            try:
                response = request.execute()
            except Exception as error:
                self._callback(request_id, None, error)
            else:
                self._callback(request_id, response, None)


class FakeService:
    def __init__(self):
        self.batch_sizes = []  # how many calls each round trip carried

    def new_batch_http_request(self, callback):
        return FakeBatch(callback, self.batch_sizes)


@pytest.fixture
def gmail():
    def build(**kwargs) -> tuple[GmailClient, FakeMessages]:
        client = GmailClient.__new__(GmailClient)  # skip the OAuth flow in __init__
        client._service = FakeService()
        client._messages = FakeMessages(**kwargs)
        return client, client._messages

    return build


def test_listing_searches_the_given_window(gmail):
    client, messages = gmail()

    ids = client.list_message_ids("from:alerts", max_results=50, days_back=7)

    assert ids == ["m1", "m2"]
    assert messages.queries == [("from:alerts newer_than:7d", 50)]


def test_timestamps_are_integer_milliseconds(gmail):
    client, _ = gmail()

    assert client.fetch_message_timestamps(["m1"]) == [("m1", 1700000000000)]


def test_full_messages_come_back_in_the_order_asked(gmail):
    client, _ = gmail()

    messages = client.fetch_full_messages(["m2", "m1"])

    assert [(m["id"], m["format"]) for m in messages] == [
        ("m2", "full"),
        ("m1", "full"),
    ]


def test_many_messages_travel_in_a_few_batches_not_one_call_each(gmail):
    client, _ = gmail()
    ids = [f"m{number}" for number in range(2 * gmail_client.BATCH_SIZE + 5)]

    assert len(client.fetch_full_messages(ids)) == len(ids)

    batch = gmail_client.BATCH_SIZE
    assert client._service.batch_sizes == [batch, batch, 5]


def test_reading_nothing_makes_no_requests(gmail):
    client, _ = gmail()

    assert client.fetch_full_messages([]) == []
    assert client.fetch_message_timestamps([]) == []
    assert client._service.batch_sizes == []


def test_an_unreadable_message_is_skipped_with_a_warning_and_the_rest_are_read(
    gmail, caplog
):
    client, _ = gmail(unreadable_ids={"bad"})

    with caplog.at_level(logging.WARNING):
        messages = client.fetch_full_messages(["a", "bad", "b"])
        timestamps = client.fetch_message_timestamps(["a", "bad", "b"])

    assert [m["id"] for m in messages] == ["a", "b"]
    assert [message_id for message_id, _ in timestamps] == ["a", "b"]
    assert "Failed to read email bad" in caplog.text


def test_messages_are_moved_to_trash_and_the_ids_reported(gmail):
    client, messages = gmail()

    trashed = client.trash_messages(["a", "b"])

    assert trashed == ["a", "b"]
    assert messages.trashed == ["a", "b"]


def test_one_failed_trash_does_not_stop_the_rest(gmail, caplog):
    client, _ = gmail(failing_ids={"a"})

    with caplog.at_level(logging.WARNING):
        trashed = client.trash_messages(["a", "b"])

    assert trashed == ["b"]  # only what was really trashed is reported
    assert "Failed to trash email a" in caplog.text


def test_verbose_trashing_logs_each_subject(gmail, caplog):
    client, _ = gmail()

    with caplog.at_level(logging.INFO):
        client.trash_messages(["m1"], verbose=True)

    assert "Trashing: Alert m1" in caplog.text


def test_trashing_nothing_makes_no_requests(gmail):
    client, messages = gmail()

    assert client.trash_messages([]) == []
    assert messages.trashed == []
    assert client._service.batch_sizes == []


def test_trashing_many_messages_is_batched(gmail):
    client, messages = gmail()
    ids = [f"m{number}" for number in range(gmail_client.BATCH_SIZE + 1)]

    assert client.trash_messages(ids) == ids
    assert client._service.batch_sizes == [gmail_client.BATCH_SIZE, 1]


def test_an_email_whose_subject_cannot_be_read_is_still_trashed(gmail):
    client, messages = gmail(unreadable_ids={"a"})

    assert client.trash_messages(["a", "b"], verbose=True) == ["a", "b"]
