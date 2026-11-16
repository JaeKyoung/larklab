"""DOI / arXiv ID / URL helpers shared by every metadata source."""

import re
from urllib.parse import parse_qs, urlparse

ARXIV_DOI_PREFIX = "10.48550/arXiv."
# bioRxiv moved from 10.1101 (shared with medRxiv) to 10.64898 in 2026.
BIORXIV_DOI_PREFIXES = ("10.1101/", "10.64898/")

_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})")
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})")
_DOI = re.compile(r"(10\.\d{4,}/[^\s?#]+)")
_PREPRINT_URL_SUFFIX = re.compile(r"\.(full(\.pdf)?|abstract|pdf)$")
_PREPRINT_VERSION_SUFFIX = re.compile(r"v\d+$")


def is_arxiv_doi(doi: str) -> bool:
    return doi.startswith(ARXIV_DOI_PREFIX)


def is_biorxiv_doi(doi: str) -> bool:
    return doi.startswith(BIORXIV_DOI_PREFIXES)


def find_arxiv_id(text: str) -> str | None:
    """Find a new-style arXiv ID (e.g. 2401.01234) in a DOI or URL."""
    match = _ARXIV_ID.search(text)
    return match.group(1) if match else None


def extract_doi(url: str) -> str | None:
    """Extract a DOI from a URL. Synthesizes the arXiv DOI for arXiv links."""
    arxiv_match = _ARXIV_URL.search(url)
    if arxiv_match:
        return f"{ARXIV_DOI_PREFIX}{arxiv_match.group(1)}"
    match = _DOI.search(url)
    if not match:
        return None
    return normalize_doi(_PREPRINT_URL_SUFFIX.sub("", match.group(1).rstrip("/")))


def normalize_doi(doi: str) -> str:
    """Drop the version suffix bioRxiv/medRxiv links carry (…123456v2)."""
    return _PREPRINT_VERSION_SUFFIX.sub("", doi) if is_biorxiv_doi(doi) else doi


def split_doi_or_url(text: str) -> tuple[str, str]:
    """Interpret CLI input as (doi, url). `url` is empty for a bare DOI."""
    text = text.strip()
    if text.startswith("10."):
        return normalize_doi(text), ""
    return extract_doi(text) or "", text


def resolve_paper_url(url: str) -> str | None:
    """Unwrap Google Scholar redirects and point preprint links at abstract pages."""
    if not url:
        return None
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if "scholar.google" in hostname and parsed.path.startswith("/scholar_url"):
        real_url = parse_qs(parsed.query).get("url", [None])[0]
        if real_url:
            url = real_url
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
    if "arxiv.org" in hostname:
        if "/pdf/" in parsed.path:
            url = url.replace("/pdf/", "/abs/", 1)
        url = re.sub(r"\.pdf$", "", url)
    if "biorxiv.org" in hostname or "medrxiv.org" in hostname:
        url = _PREPRINT_URL_SUFFIX.sub("", url)
    return url
