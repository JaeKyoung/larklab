"""PubMed E-utilities: look up a paper by DOI or title, and crawl a day's papers."""

import logging
import time
import warnings
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from itertools import batched
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from larklab.models import JOURNAL_SOURCE_PREFIX, CrawlResult, Paper
from larklab.sources.papers import crawl_window
from larklab.utils.http import build_http_client
from larklab.utils.text import canonical_journal_name, normalize_title

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES: list[str] = []  # no journal filter: every paper with an abstract

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 1.0  # NCBI allows ~3 requests/s without an API key
_REQUEST_PAUSE_SECONDS = 0.4  # between the requests of a crawl, for the same reason
_MAX_IDS = 10000  # esearch returns no more than this for one query; a day has <7000
_FETCH_BATCH_SIZE = 200  # records per efetch request
_MAX_RESULTS = 4000  # about one busy day; a crawl never stops in the middle of one
_PUBMED_TIMEZONE = ZoneInfo("America/New_York")  # where PubMed's days begin and end


def fetch_by_doi(client: httpx.Client, doi: str) -> Paper | None:
    """Return the PubMed record for a DOI, or None if PubMed does not know it."""
    paper = _fetch_first_match(client, f"{doi}[doi]")
    if paper:
        paper.doi = doi
    return paper


def fetch_by_title(client: httpx.Client, title: str) -> Paper | None:
    """Return the best PubMed match for a title (DOI is filled when PubMed has it)."""
    return _fetch_first_match(client, f"{title}[Title]")


def crawl_recent(
    categories: list[str] | None = None,
    days_back: int = 1,
    max_results: int = _MAX_RESULTS,
    since: datetime | None = None,
) -> CrawlResult:
    """Collect the papers added to PubMed in the last `days_back` full days.

    With `since` it resumes the day after the last one already handled instead,
    catching up on missed days (at most a week). `categories` are journal names or
    abbreviations; without them every paper that has an abstract and a DOI comes
    back (3000 to 6000 a day), except preprints. Days are PubMed's own (US Eastern)
    and only finished days are read, so a paper indexed late in the evening is not
    skipped. The crawl
    never stops in the middle of a day, so `max_results` can be passed by one day.
    The result is marked incomplete when PubMed kept failing, so the caller does
    not treat the papers as seen.
    """
    window = crawl_window(
        datetime.now(_PUBMED_TIMEZONE).date() - timedelta(days=1), days_back, since
    )
    if window is None:
        return CrawlResult([])
    day, end = window

    papers: dict[str, Paper] = {}  # by normalized title: the first one wins
    complete = True
    with build_http_client(timeout=60) as client:
        journal_terms = _journal_terms(client, categories or [])
        if categories and not journal_terms:
            return CrawlResult([])  # never fall back to all of PubMed on a typo
        while day <= end and len(papers) < max_results:
            day_papers = _papers_added_on(client, day, journal_terms)
            if day_papers is None:
                complete = False
                break
            for paper in day_papers:
                papers.setdefault(normalize_title(paper.title), paper)
            day += timedelta(days=1)
    return CrawlResult(list(papers.values()), complete=complete)


def _papers_added_on(
    client: httpx.Client, day: date, journal_terms: list[str]
) -> list[Paper] | None:
    """Every paper added on `day` that has a title, abstract and DOI; None when
    PubMed kept failing."""
    found = _esearch(client, _day_query(day, journal_terms), retmax=str(_MAX_IDS))
    if found is None:
        return None
    ids = found.get("idlist", [])
    if int(found.get("count", 0)) > len(ids):
        logger.warning(
            "PubMed %s: only the first %d papers can be read.", day, len(ids)
        )
    added_at = datetime(day.year, day.month, day.day, tzinfo=UTC)
    papers = []
    for chunk in batched(ids, _FETCH_BATCH_SIZE):
        response = _get(client, _EFETCH_URL, _efetch_params(chunk))
        if response is None:
            return None
        for paper in _parse_articles(response.text):
            if paper.title and paper.abstract and paper.doi:
                paper.published_at = added_at
                papers.append(paper)
        time.sleep(_REQUEST_PAUSE_SECONDS)
    logger.info("PubMed %s: %d papers, %d usable", day, len(ids), len(papers))
    return papers


def _day_query(day: date, journal_terms: list[str]) -> str:
    stamp = day.strftime("%Y/%m/%d")  # "edat": the day PubMed added the record
    query = f'hasabstract AND ("{stamp}"[edat] : "{stamp}"[edat])'
    if journal_terms:
        query += " AND (" + " OR ".join(journal_terms) + ")"
    else:
        # PubMed adds bioRxiv/medRxiv/arXiv preprints weeks late, hundreds in one
        # day: they come from their own sources, on time, and would repeat here.
        query += " NOT preprint[pt]"
    return query


def _journal_terms(client: httpx.Client, journals: list[str]) -> list[str]:
    """Search terms for the journals asked for.

    An exact title or abbreviation matches itself ("Bioinformatics", "Chem Sci").
    Any other spelling goes to PubMed unquoted, which maps it to the journal on its
    own ("Protein science" -> "protein sci"); the mapping is logged. A name PubMed
    cannot place is warned about and left out, so a typo never matches nothing
    quietly, every day.
    """
    terms = []
    for journal in journals:
        name = journal.replace('"', "").strip()
        exact = _count_and_translation(client, f'"{name}"[jour]')
        if exact is None or exact[0] > 0:  # None: PubMed did not answer; try it anyway
            terms.append(f'"{name}"[jour]')
            continue
        mapped = _count_and_translation(client, f"{name}[jour]")
        if mapped and mapped[0] > 0:
            logger.info("PubMed reads %r as %s", name, mapped[1])
            terms.append(f"{name}[jour]")
        else:
            logger.warning("PubMed has no journal called %r; it is left out.", name)
    return terms


def _count_and_translation(client: httpx.Client, term: str) -> tuple[int, str] | None:
    """How many records match, and how PubMed read the term; None if unknown."""
    found = _esearch(client, term, retmax="0")
    time.sleep(_REQUEST_PAUSE_SECONDS)
    if found is None or "count" not in found:
        return None
    return int(found["count"]), found.get("querytranslation", "")


def _fetch_first_match(client: httpx.Client, query: str) -> Paper | None:
    pmids = _search_pmids(client, query)
    if not pmids:
        return None
    response = _get(client, _EFETCH_URL, _efetch_params(pmids[:1]))
    if response is None:
        return None
    paper = _paper_from_article(_parse_xml(response.text))
    return paper if paper.title else None


def _search_pmids(client: httpx.Client, query: str) -> list[str]:
    found = _esearch(client, query)
    return found.get("idlist", []) if found else []


def _esearch(client: httpx.Client, term: str, **params: str) -> dict | None:
    """The `esearchresult` of a PubMed search; None when PubMed failed or answered
    in an unexpected shape."""
    response = _get(
        client,
        _ESEARCH_URL,
        {"db": "pubmed", "term": term, "retmode": "json", **params},
    )
    if response is None:
        return None
    try:
        return response.json()["esearchresult"]
    except (KeyError, ValueError) as error:
        logger.debug("PubMed esearch returned unexpected data for %s: %s", term, error)
        return None


def _efetch_params(ids: Iterable[str]) -> dict[str, str]:
    return {
        "db": "pubmed",
        "id": ",".join(ids),
        "rettype": "abstract",
        "retmode": "xml",
    }


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


def _parse_articles(xml: str) -> list[Paper]:
    """The papers of an efetch response; the source of each names its journal by
    the short name (`pubmed:Chem Sci`)."""
    papers = []
    for article in _parse_xml(xml).find_all("pubmedarticle"):
        paper = _paper_from_article(article)
        short_name = article.find("isoabbreviation")
        paper.source = JOURNAL_SOURCE_PREFIX + (
            short_name.text if short_name else paper.journal
        )
        papers.append(paper)
    return papers


def _parse_xml(xml: str) -> BeautifulSoup:
    # html.parser lowercases tag names (articletitle, abstracttext, ...). It also
    # warns that the input is XML, which is expected here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(xml, "html.parser")


def _paper_from_article(soup: Tag) -> Paper:
    title = soup.find("articletitle")
    journal = soup.find("journal")
    journal_title = journal.find("title") if journal else None
    # The article's own ids only: the reference list further down has DOIs too.
    pubmed_data = soup.find("pubmeddata")
    own_ids = (
        pubmed_data.find("articleidlist", recursive=False) if pubmed_data else None
    )
    doi = own_ids.find("articleid", idtype="doi") if own_ids else None
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
        journal=canonical_journal_name(journal_title.text if journal_title else ""),
        abstract=" ".join(section for section in abstract_sections if section),
        doi=doi.text if doi else "",
    )


def _format_author(author: Tag) -> str:
    last_name = author.find("lastname").text
    first_name = author.find("forename")
    return f"{last_name}, {first_name.text}" if first_name else last_name
