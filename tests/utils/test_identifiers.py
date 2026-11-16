import pytest

from larklab.utils.identifiers import (
    extract_doi,
    find_arxiv_id,
    is_arxiv_doi,
    is_biorxiv_doi,
    normalize_doi,
    resolve_paper_url,
    split_doi_or_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://arxiv.org/abs/2401.01234", "10.48550/arXiv.2401.01234"),
        ("https://arxiv.org/pdf/2401.01234v2", "10.48550/arXiv.2401.01234"),
        ("https://doi.org/10.1038/s41586-021-03819-2", "10.1038/s41586-021-03819-2"),
        (
            "https://www.biorxiv.org/content/10.1101/2024.01.01.123456v2.full.pdf",
            "10.1101/2024.01.01.123456",
        ),
        (
            "https://www.biorxiv.org/content/10.64898/2026.11.12.766037v1.full",
            "10.64898/2026.11.12.766037",
        ),
        ("https://example.com/no-doi-here", None),
    ],
)
def test_extract_doi(url, expected):
    assert extract_doi(url) == expected


def test_extract_doi_keeps_version_like_suffix_on_journal_dois():
    assert extract_doi("https://doi.org/10.1234/abc.v2") == "10.1234/abc.v2"


def test_bare_biorxiv_dois_lose_their_version_suffix():
    assert split_doi_or_url("10.1101/2024.01.01.123456v1") == (
        "10.1101/2024.01.01.123456",
        "",
    )
    assert normalize_doi("10.64898/2026.11.12.766037v3") == "10.64898/2026.11.12.766037"
    assert (
        normalize_doi("10.1234/abc.v2") == "10.1234/abc.v2"
    )  # other publishers untouched


def test_split_doi_or_url():
    assert split_doi_or_url("10.1038/xyz") == ("10.1038/xyz", "")
    assert split_doi_or_url("https://doi.org/10.1038/xyz") == (
        "10.1038/xyz",
        "https://doi.org/10.1038/xyz",
    )
    assert split_doi_or_url("https://example.com/paper") == (
        "",
        "https://example.com/paper",
    )


def test_doi_prefix_checks_include_the_2026_biorxiv_prefix():
    assert is_biorxiv_doi("10.1101/2020.01.01.000001")
    assert is_biorxiv_doi("10.64898/2026.11.12.766037")
    assert not is_biorxiv_doi("10.1038/s41586-021-03819-2")
    assert is_arxiv_doi("10.48550/arXiv.2401.01234")
    assert not is_arxiv_doi("10.1101/2020.01.01.000001")


def test_find_arxiv_id():
    assert find_arxiv_id("10.48550/arXiv.2401.01234") == "2401.01234"
    assert find_arxiv_id("https://arxiv.org/abs/2401.01234v3") == "2401.01234"
    assert find_arxiv_id("10.1038/nothing") is None


def test_resolve_paper_url_unwraps_scholar_redirects():
    redirect = (
        "https://scholar.google.com/scholar_url"
        "?url=https://arxiv.org/pdf/2401.01234&hl=en"
    )
    assert resolve_paper_url(redirect) == "https://arxiv.org/abs/2401.01234"


def test_resolve_paper_url_points_preprints_at_abstract_pages():
    assert (
        resolve_paper_url(
            "https://www.biorxiv.org/content/10.1101/2024.01.01.1v1.full.pdf"
        )
        == "https://www.biorxiv.org/content/10.1101/2024.01.01.1v1"
    )
    assert resolve_paper_url("https://example.com/a.pdf") == "https://example.com/a.pdf"
    assert resolve_paper_url("") is None
