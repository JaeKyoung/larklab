"""Remember how far each source has been crawled, so a paper is recommended once.

Without this, a fixed "yesterday" window both misses papers (arXiv only lists
announced papers, a day or more late) and repeats them (weekend runs see the same
batch again). The state is one small JSON file: per source the newest paper handled
and, for sources that are read a little further back each time, the papers seen.
"""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from larklab.models import SourceProgress
from larklab.utils.files import read_json_or, write_text_atomically


def load_progress(path: Path) -> dict[str, SourceProgress]:
    """Progress per source; empty if nothing is saved.

    A missing or unreadable file means "start fresh" — never an error, because
    the worst outcome is recommending a few papers twice.
    """
    return read_json_or(path, _parse, default={}, what="progress")


def advance_progress(path: Path, updates: dict[str, SourceProgress]) -> None:
    """Replace the progress of the updated sources; a resume point never moves
    backwards."""
    saved = load_progress(path)
    for source, progress in updates.items():
        before = saved.get(source)
        if before:
            progress = replace(progress, newest=max(before.newest, progress.newest))
        saved[source] = progress
    write_text_atomically(
        path, json.dumps({s: _dump(p) for s, p in saved.items()}, indent=2)
    )


def _parse(raw: dict) -> dict[str, SourceProgress]:
    return {
        source: SourceProgress(
            newest=datetime.fromisoformat(entry["newest"]),
            seen={
                doi: datetime.fromisoformat(moment)
                for doi, moment in entry["seen"].items()
            },
        )
        for source, entry in raw.items()
    }


def _dump(progress: SourceProgress) -> dict:
    return {
        "newest": progress.newest.isoformat(),
        "seen": {doi: moment.isoformat() for doi, moment in progress.seen.items()},
    }
