"""Gmail API client: list, fetch, parse, and trash Google Scholar alert emails."""

import logging
from itertools import batched
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from larklab.config import Config
from larklab.models import ScholarPaper
from larklab.sources.gmail.scholar_alert_parser import parse_scholar_email

logger = logging.getLogger(__name__)

# The `send` scope is intentionally excluded: this tool only reads and trashes.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


# Gmail accepts 100 calls per batch request. Fewer per batch keeps the burst
# under its per-second quota (a `get` costs 5 units of 250 per second).
BATCH_SIZE = 20


class GmailClient:
    def __init__(self, config: Config):
        self._service = _authenticate(config)
        self._messages = self._service.users().messages()

    def list_message_ids(
        self, query: str, max_results: int, days_back: int
    ) -> list[str]:
        response = self._messages.list(
            userId="me", q=f"{query} newer_than:{days_back}d", maxResults=max_results
        ).execute()
        return [message["id"] for message in response.get("messages", [])]

    def fetch_message_timestamps(self, message_ids: list[str]) -> list[tuple[str, int]]:
        """(message id, received time in epoch milliseconds) for each message that
        could be read."""
        messages = self._get_each(message_ids, format="minimal")
        return [
            (mid, int(message["internalDate"])) for mid, message in messages.items()
        ]

    def fetch_full_messages(self, message_ids: list[str]) -> list[dict]:
        """The messages that could be read. One that cannot be (it is skipped with
        a warning) stays in the inbox and is picked up by the next run."""
        return list(self._get_each(message_ids, format="full").values())

    def parse_emails(self, raw_messages: list[dict]) -> list[ScholarPaper]:
        """Parse raw Gmail messages into ScholarPapers (the only entry point to
        the fragile Scholar HTML parser)."""
        return [
            paper for message in raw_messages for paper in parse_scholar_email(message)
        ]

    def trash_messages(
        self, message_ids: list[str], verbose: bool = False
    ) -> list[str]:
        """Move messages to trash (recoverable). Returns the ids that were trashed."""
        if verbose:
            for subject in self._subjects_of(message_ids).values():
                logger.info("  Trashing: %s", subject)
        trashed = self._send_in_batches(
            {mid: self._messages.trash(userId="me", id=mid) for mid in message_ids},
            action="trash",
        )
        return list(trashed)

    def _subjects_of(self, message_ids: list[str]) -> dict[str, str]:
        metadata = self._get_each(
            message_ids, format="metadata", metadataHeaders=["Subject"]
        )
        return {
            message_id: next(
                (
                    header["value"]
                    for header in message["payload"]["headers"]
                    if header["name"] == "Subject"
                ),
                "(no subject)",
            )
            for message_id, message in metadata.items()
        }

    def _get_each(self, message_ids: list[str], **params) -> dict[str, dict]:
        return self._send_in_batches(
            {
                message_id: self._messages.get(userId="me", id=message_id, **params)
                for message_id in message_ids
            },
            action="read",
        )

    def _send_in_batches(self, requests: dict, action: str) -> dict[str, dict]:
        """Send requests (keyed by message id) BATCH_SIZE at a time, one HTTP round
        trip per batch. Returns the responses of those that succeeded, in request
        order; the others are logged and left out, so one bad email never blocks
        the rest."""
        responses: dict[str, dict] = {}

        def collect(message_id, response, error):
            if error is None:
                responses[message_id] = response
            else:
                logger.warning("  Failed to %s email %s: %s", action, message_id, error)

        for chunk in batched(requests.items(), BATCH_SIZE):
            batch = self._service.new_batch_http_request(callback=collect)
            for message_id, request in chunk:
                batch.add(request, request_id=message_id)
            batch.execute()
        return {mid: responses[mid] for mid in requests if mid in responses}


def _authenticate(config: Config):
    """Return a Gmail API service, running the OAuth flow if the token is stale."""
    token_file = Path(config.token_path)
    credentials = None
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.credentials_path, SCOPES
            )
            credentials = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json())
        token_file.chmod(0o600)  # holds a refresh token

    return build("gmail", "v1", credentials=credentials)
