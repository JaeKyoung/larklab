import pytest

from larklab.utils.text import (
    canonical_journal_name,
    collapse_whitespace,
    normalize_title,
)


def test_normalize_title_ignores_case_punctuation_and_spacing():
    stored = "De novo design of protein structure and function with RFdiffusion."
    crawled = "De novo design of protein structure and function with  RFdiffusion"
    assert normalize_title(stored) == normalize_title(crawled)
    assert normalize_title("Deep-Learning for Proteins") == normalize_title(
        "deep learning for proteins"
    )


def test_normalize_title_keeps_different_titles_apart():
    assert normalize_title("Protein design") != normalize_title("Protein folding")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Biorxiv", "bioRxiv"),
        ("bioRxiv : the preprint server for biology", "bioRxiv"),
        ("medrxiv", "medRxiv"),
        ("arxiv", "arXiv"),
        ("Nature Methods", "Nature Methods"),
        ("", ""),
    ],
)
def test_canonical_journal_name(raw, expected):
    assert canonical_journal_name(raw) == expected


def test_collapse_whitespace_joins_wrapped_lines():
    assert collapse_whitespace("A title\n  wrapped  over\tlines") == (
        "A title wrapped over lines"
    )
