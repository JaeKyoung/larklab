"""Remember how far each source has been crawled, so a paper is recommended once.

Without this, a fixed "yesterday" window both misses papers (arXiv only lists
announced papers, a day or more late) and repeats them (weekend runs see the same
batch again). The state is one timestamp per source in a small JSON file.
"""

import json
from datetime import datetime
from pathlib import Path

from larklab.utils.files import read_json_or, write_text_atomically


def load_progress(path: Path) -> dict[str, datetime]:
    """Newest paper time already handled per source; empty if nothing is saved.

    A missing or unreadable file means "start fresh" — never an error, because
    the worst outcome is recommending a few papers twice.
    """
    return read_json_or(
        path,
        lambda raw: {
            source: datetime.fromisoformat(stamp) for source, stamp in raw.items()
        },
        default={},
        what="progress",
    )


def advance_progress(path: Path, newest: dict[str, datetime]) -> None:
    """Move each source's resume point forward to `newest` (never backwards)."""
    saved = load_progress(path)
    for source, moment in newest.items():
        saved[source] = max(saved.get(source, moment), moment)
    write_text_atomically(
        path, json.dumps({s: m.isoformat() for s, m in saved.items()}, indent=2)
    )
