"""PubMed E-utilities: look up a paper by DOI or title."""

import logging
import time
import warnings

import httpx
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from larklab.models import Paper

logger = logging.getLogger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 1.0  # NCBI allows ~3 requests/s without an API key


def fetch_by_doi(client: httpx.Client, doi: str) -> Paper | None:
    """Return the PubMed record for a DOI, or None if PubMed does not know it."""
    paper = _fetch_first_match(client, f"{doi}[doi]")
    if paper:
        paper.doi = doi
    return paper


def fetch_by_title(client: httpx.Client, title: str) -> Paper | None:
    """Return the best PubMed match for a title (DOI is filled when PubMed has it)."""
    return _fetch_first_match(client, f"{title}[Title]")


def _fetch_first_match(client: httpx.Client, query: str) -> Paper | None:
    pmids = _search_pmids(client, query)
    if not pmids:
        return None
    response = _get(client, _EFETCH_URL, _efetch_params(pmids[0]))
    if response is None:
        return None
    paper = _parse_article_xml(response.text)
    return paper if paper.title else None


def _search_pmids(client: httpx.Client, query: str) -> list[str]:
    response = _get(
        client, _ESEARCH_URL, {"db": "pubmed", "term": query, "retmode": "json"}
    )
    if response is None:
        return []
    try:
        return response.json()["esearchresult"]["idlist"]
    except (KeyError, ValueError) as error:
        logger.debug("PubMed esearch returned unexpected data for %s: %s", query, error)
        return []


def _efetch_params(pmid: str) -> dict[str, str]:
    return {"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "xml"}


def _get(
    client: httpx.Client, url: str, params: dict[str, str]
) -> httpx.Response | None:
    """GET with retry on rate limiting / server errors. Returns None on failure."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as error:
            logger.debug("PubMed request failed: %s", error)
            return None
        if response.status_code not in _RETRYABLE_STATUS_CODES:
            return response if response.is_success else None
        if attempt < _MAX_ATTEMPTS:
            time.sleep(_BACKOFF_SECONDS * attempt)
    logger.debug("PubMed still failing after %d attempts", _MAX_ATTEMPTS)
    return None


def _parse_article_xml(xml: str) -> Paper:
    # html.parser lowercases tag names (articletitle, abstracttext, ...). It also
    # warns that the input is XML, which is expected here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(xml, "html.parser")

    title = soup.find("articletitle")
    journal = soup.find("journal")
    journal_title = journal.find("title") if journal else None
    doi = soup.find("articleid", idtype="doi")
    # Structured abstracts (Background/Methods/Results/...) span several tags. Look
    # only inside the article's own <Abstract>: <OtherAbstract> holds translations
    # and plain-language summaries.
    abstract = soup.find("abstract")
    abstract_sections = (
        [tag.text.strip() for tag in abstract.find_all("abstracttext")]
        if abstract
        else []
    )

    return Paper(
        title=title.text if title else "",
        authors=[
            _format_author(a) for a in soup.find_all("author") if a.find("lastname")
        ],
        journal=journal_title.text if journal_title else "",
        abstract=" ".join(section for section in abstract_sections if section),
        doi=doi.text if doi else "",
    )


def _format_author(author: Tag) -> str:
    last_name = author.find("lastname").text
    first_name = author.find("forename")
    return f"{last_name}, {first_name.text}" if first_name else last_name
