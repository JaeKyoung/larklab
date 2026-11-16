"""Move one Gmail message to trash (recoverable, not a permanent delete).

Manual helper against the live Gmail account:
    pixi run python scripts/manual/trash_email.py <message_id>
"""

import sys

from larklab.config import load_config
from larklab.sources.gmail.client import GmailClient


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/manual/trash_email.py <message_id>")

    message_id = sys.argv[1]
    trashed = GmailClient(load_config()).trash_messages([message_id])
    print(f"Moved to trash: {message_id}" if trashed else f"Failed: {message_id}")


if __name__ == "__main__":
    main()
