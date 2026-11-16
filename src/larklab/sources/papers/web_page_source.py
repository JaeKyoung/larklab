"""Publisher web pages: scrape metadata and abstracts as a last resort."""

import logging
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from larklab.models import Paper
from larklab.utils.text import canonical_journal_name, collapse_whitespace

logger = logging.getLogger(__name__)

_HTML_HEADERS = {"Accept": "text/html"}
_RETRY_DELAY_SECONDS = 2.0
_ABSTRACT_META_NAMES = ("citation_abstract", "og:description", "description")


def fetch_paper(client: httpx.Client, url: str, doi: str = "") -> Paper | None:
    """Build a Paper from a page's citation_* meta tags, or None if unreadable."""
    soup = _download(client, url)
    if soup is None:
        return None
    if soup.select_one("#challenge-error-text"):
        logger.debug("Blocked by Cloudflare: %s", url)
        return None

    title = _meta_content(soup, "citation_title", "og:title")
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    if not title:
        return None

    authors = [
        tag["content"].strip()
        for tag in soup.find_all("meta", attrs={"name": "citation_author"})
        if tag.get("content")
    ]
    return Paper(
        title=title,
        authors=authors,
        journal=_meta_content(soup, "citation_journal_title")
        or _preprint_server_name(url),
        abstract=extract_abstract(soup, url) or "",
        doi=doi or _meta_content(soup, "citation_doi"),
    )


def fetch_abstract(client: httpx.Client, url: str) -> str | None:
    """Fetch a page and extract its abstract. Retries transient network errors."""
    soup = _download(client, url, max_retries=2)
    if soup is None:
        return None
    try:
        return extract_abstract(soup, url)
    except ValueError as error:
        logger.debug("Could not parse %s (likely a binary response): %s", url, error)
        return None


def extract_abstract(soup: BeautifulSoup, url: str) -> str | None:
    """Site-specific abstract parsing with a generic meta-tag fallback."""
    hostname = urlparse(url).hostname or ""
    if "arxiv.org" in hostname:
        return _arxiv_abstract(soup)
    if "pubmed" in hostname:
        return _pubmed_abstract(soup)
    if "nature.com" in hostname:
        return _nature_abstract(soup) or _meta_content(soup, *_ABSTRACT_META_NAMES)
    return _meta_content(soup, *_ABSTRACT_META_NAMES) or None


def _download(
    client: httpx.Client, url: str, max_retries: int = 0
) -> BeautifulSoup | None:
    """GET a page and parse it. Client errors (4xx) are final; others retry."""
    for attempt in range(max_retries + 1):
        try:
            response = client.get(url, headers=_HTML_HEADERS)
            if 400 <= response.status_code < 500:
                logger.debug("Client error %d for %s", response.status_code, url)
                return None
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            if attempt < max_retries:
                logger.debug("Retry %d for %s: %s", attempt + 1, url, error)
                time.sleep(_RETRY_DELAY_SECONDS)
            else:
                logger.debug("Giving up on %s: %s", url, error)
    return None


def _meta_content(soup: BeautifulSoup, *names: str) -> str:
    """First non-empty <meta> content among `names` (matched as name= or property=)."""
    for name in names:
        tag = soup.find("meta", attrs={"name": name}) or soup.find(
            "meta", attrs={"property": name}
        )
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _preprint_server_name(url: str) -> str:
    """'arXiv' / 'bioRxiv' / 'medRxiv' for those sites' URLs, else ''."""
    hostname = urlparse(url).hostname or ""
    name = canonical_journal_name(hostname)
    return name if name != hostname else ""


def _arxiv_abstract(soup: BeautifulSoup) -> str | None:
    block = soup.find("blockquote", class_="abstract")
    if not block:
        return None
    label = block.find("span", class_="descriptor")  # the leading "Abstract:"
    if label:
        label.decompose()
    return collapse_whitespace(block.get_text())


def _pubmed_abstract(soup: BeautifulSoup) -> str | None:
    block = soup.find("div", class_="abstract-content")
    return collapse_whitespace(block.get_text()) if block else None


def _nature_abstract(soup: BeautifulSoup) -> str | None:
    block = soup.select_one("#Abs1-content")
    if not block:
        return None
    for footnote in block.find_all("sup"):
        footnote.decompose()
    return collapse_whitespace(block.get_text())
