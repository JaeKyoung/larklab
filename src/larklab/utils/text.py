"""Text helpers for comparing and cleaning paper metadata."""

import re

_PREPRINT_SERVER_NAMES = (
    ("biorxiv", "bioRxiv"),
    ("medrxiv", "medRxiv"),
    ("arxiv", "arXiv"),
)


def collapse_whitespace(text: str) -> str:
    """Replace runs of whitespace (including newlines) with a single space."""
    return " ".join(text.split())


def normalize_title(title: str) -> str:
    """Case-, punctuation- and whitespace-insensitive key for matching titles."""
    return collapse_whitespace(re.sub(r"[^\w\s]", " ", title.lower()))


def canonical_journal_name(journal: str) -> str:
    """Give preprint servers one spelling (sources disagree: 'Biorxiv',
    'bioRxiv : the preprint server for biology', ...). Other journals pass through."""
    lowered = journal.lower()
    for marker, name in _PREPRINT_SERVER_NAMES:
        if marker in lowered:
            return name
    return journal
