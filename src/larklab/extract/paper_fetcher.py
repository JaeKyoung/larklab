"""Fetch paper metadata by DOI or URL.

Priority: PubMed → arXiv → bioRxiv → CrossRef → HTML.
"""

import logging
import re
import warnings
from datetime import date

import arxiv
import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from larklab.extract.abstract_fetcher import pubmed_efetch, pubmed_esearch
from larklab.extract.normalizers import clean_biorxiv_abstract, clean_crossref_abstract
from larklab.schemas import Paper

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; larklab/0.1)",
    "Accept": "text/html",
}


def _make_paper(
    title: str = "",
    authors: list[str] | None = None,
    journal: str = "",
    abstract: str = "",
    doi: str = "",
) -> Paper:
    return Paper(
        title=title,
        authors=authors or [],
        journal=journal,
        abstract=abstract,
        doi=doi,
    )


def paper_from_arxiv_result(r: arxiv.Result) -> Paper:
    """Convert an arxiv.Result to a Paper."""
    arxiv_id = r.get_short_id().split("v")[0]
    pub = r.published.date() if r.published else None
    return Paper(
        title=r.title.replace("\n", " "),
        authors=[a.name for a in r.authors],
        journal="arXiv",
        abstract=r.summary.replace("\n", " "),
        doi=r.doi or f"10.48550/arXiv.{arxiv_id}",
        published_date=pub,
    )


def paper_from_biorxiv_entry(entry: dict) -> Paper:
    """Convert a bioRxiv API collection entry to a Paper."""
    pub = None
    if entry.get("date"):
        try:
            pub = date.fromisoformat(entry["date"])
        except ValueError:
            pass
    return Paper(
        title=entry.get("title", "").strip(),
        authors=[a.strip() for a in entry.get("authors", "").split(";")],
        journal=entry.get("server", "biorxiv").capitalize(),
        abstract=clean_biorxiv_abstract(entry.get("abstract", "")),
        doi=entry.get("doi", ""),
        published_date=pub,
    )


def fetch_paper(doi: str, url: str = "") -> Paper:
    """Fetch paper metadata by DOI. Falls back to URL if DOI unavailable.

    Priority: PubMed → arXiv → bioRxiv → CrossRef → HTML.
    """
    if doi:
        result = _fetch_from_pubmed(doi)
        if result and result.title:
            result.doi = doi
            return result

    if doi and doi.startswith("10.48550/arXiv"):
        result = _fetch_from_arxiv_api(doi)
        if result and result.title:
            return result
        if not url:
            match = re.search(r"(\d{4}\.\d{4,5})", doi)
            if match:
                url = f"https://arxiv.org/abs/{match.group(1)}"
    elif url and "arxiv.org" in url:
        result = _fetch_from_arxiv_api(url)
        if result and result.title:
            return result

    if doi and doi.startswith("10.1101/"):
        result = _fetch_from_biorxiv_api(doi)
        if result and result.title:
            return result
    elif url and ("biorxiv.org" in url or "medrxiv.org" in url):
        result = _fetch_from_biorxiv_api(url)
        if result and result.title:
            return result

    if doi:
        result = _fetch_from_crossref(doi)
        if result and result.title:
            return result

    if url:
        return _fetch_from_html(url, doi)

    return _make_paper(doi=doi or "")


def _fetch_from_crossref(doi: str) -> Paper:
    try:
        api_url = f"https://api.crossref.org/works/{doi}"
        resp = httpx.get(api_url, timeout=15)
        if resp.status_code != 200:
            logger.debug("CrossRef API returned %d for %s", resp.status_code, doi)
            return _make_paper(doi=doi or "")

        data = resp.json()["message"]
        title = (data.get("title") or [""])[0]
        authors = [
            f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
            for a in data.get("author", [])
        ]
        journal = (data.get("container-title") or [""])[0]
        abstract = clean_crossref_abstract(data.get("abstract", ""))

        return _make_paper(
            title=title,
            authors=authors,
            journal=journal,
            abstract=abstract,
            doi=doi,
        )
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.debug("CrossRef fetch failed for %s: %s", doi, e)
        return _make_paper(doi=doi or "")


def _fetch_from_html(url: str, doi: str | None) -> Paper:
    try:
        with httpx.Client(
            follow_redirects=True, timeout=15, headers=_HEADERS
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
        logger.debug("HTML fetch failed for %s: %s", url, e)
        return _make_paper(doi=doi or "")

    soup = BeautifulSoup(resp.text, "html.parser")

    if soup.select_one("#challenge-error-text"):
        logger.debug("Blocked by Cloudflare: %s", url)
        return _make_paper(doi=doi or "")

    title = ""
    meta_title = soup.find("meta", attrs={"name": "citation_title"}) or soup.find(
        "meta", attrs={"property": "og:title"}
    )
    if meta_title and meta_title.get("content"):
        title = meta_title["content"].strip()
    elif soup.title:
        title = soup.title.get_text(strip=True)

    authors = [
        tag["content"].strip()
        for tag in soup.find_all("meta", attrs={"name": "citation_author"})
        if tag.get("content")
    ]

    journal_tag = soup.find("meta", attrs={"name": "citation_journal_title"})
    journal = ""
    if journal_tag and journal_tag.get("content"):
        journal = journal_tag["content"].strip()
    elif "arxiv.org" in url:
        journal = "arXiv"
    elif "biorxiv.org" in url:
        journal = "bioRxiv"
    elif "medrxiv.org" in url:
        journal = "medRxiv"

    if not doi:
        doi_tag = soup.find("meta", attrs={"name": "citation_doi"})
        if doi_tag and doi_tag.get("content"):
            doi = doi_tag["content"].strip()

    abstract = _parse_abstract_from_meta(soup)

    return _make_paper(
        title=title, authors=authors, journal=journal, abstract=abstract, doi=doi or ""
    )


def _parse_abstract_from_meta(soup: BeautifulSoup) -> str:
    """Extract abstract from HTML meta tags."""
    for name in ("citation_abstract", "og:description", "description"):
        meta = soup.find("meta", attrs={"name": name}) or soup.find(
            "meta", attrs={"property": name}
        )
        if meta and meta.get("content"):
            return meta["content"].strip()
    return ""


def _fetch_from_pubmed(doi: str) -> Paper | None:
    with httpx.Client(timeout=15) as client:
        ids = pubmed_esearch(client, f"{doi}[doi]")
        if not ids:
            return None
        soup = pubmed_efetch(client, ids[0])
    if not soup:
        return None

    title_tag = soup.find("articletitle")
    title = title_tag.text if title_tag else ""

    authors = []
    for a in soup.find_all("author"):
        last = a.find("lastname")
        first = a.find("forename")
        if last:
            name = last.text
            if first:
                name += f", {first.text}"
            authors.append(name)

    journal = ""
    journal_el = soup.find("journal")
    if journal_el:
        jtitle = journal_el.find("title")
        if jtitle:
            journal = jtitle.text

    abstract_tag = soup.find("abstracttext")
    abstract = abstract_tag.text if abstract_tag else ""

    return _make_paper(
        title=title,
        authors=authors,
        journal=journal,
        abstract=abstract,
        doi=doi,
    )


def _fetch_from_arxiv_api(url: str) -> Paper:
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", url)
    if not match:
        logger.debug("Could not extract arXiv ID from %s", url)
        return _make_paper()

    arxiv_id = match.group(1)
    doi = f"10.48550/arXiv.{arxiv_id}"
    try:
        client = arxiv.Client()
        search = arxiv.Search(id_list=[arxiv_id])
        results = list(client.results(search))

        if not results:
            logger.debug("No results from arXiv API for %s", arxiv_id)
            return _make_paper(doi=doi)

        return paper_from_arxiv_result(results[0])
    except (arxiv.HTTPError, arxiv.UnexpectedEmptyPageError) as e:
        logger.debug("arXiv API failed for %s: %s", arxiv_id, e)
        return _make_paper(doi=doi)


def _fetch_from_biorxiv_api(url: str) -> Paper:
    match = re.search(r"(10\.\d{4,}/[\d.]+)", url)
    if not match:
        logger.debug("Could not extract DOI from %s", url)
        return _make_paper()

    doi = match.group(1)
    try:
        api_url = f"https://api.biorxiv.org/details/biorxiv/{doi}"

        resp = httpx.get(api_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("collection"):
            logger.debug("No results from bioRxiv API for %s", doi)
            return _make_paper(doi=doi)

        paper = paper_from_biorxiv_entry(data["collection"][-1])
        paper.doi = doi
        return paper
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.debug("bioRxiv fetch failed for %s: %s", url, e)
        return _make_paper(doi=doi)
