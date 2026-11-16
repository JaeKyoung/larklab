"""Resolve a DOI or URL into paper metadata by consulting several sources.

Sources are tried in order — PubMed, arXiv, CrossRef, bioRxiv — and each later
source only fills fields the earlier ones left empty. The lookup stops as soon
as the record is complete. CrossRef comes before bioRxiv because it carries the
complete author list (the bioRxiv API returned 45 of 61 authors for one paper)
and names the posting server for preprints; bioRxiv fills whatever is missing.

A publisher web page is the last resort, used only when no source found a title.
"""

import logging
from collections.abc import Callable
from dataclasses import replace

import httpx

from larklab.models import Paper
from larklab.sources.papers import (
    arxiv_source,
    biorxiv_source,
    crossref_source,
    pubmed_source,
    web_page_source,
)
from larklab.utils.http import build_http_client
from larklab.utils.identifiers import (
    extract_doi,
    find_arxiv_id,
    is_arxiv_doi,
    is_biorxiv_doi,
    normalize_doi,
)
from larklab.utils.text import canonical_journal_name

logger = logging.getLogger(__name__)

Lookup = Callable[[], Paper | None]


def fetch_paper_metadata(
    doi: str = "",
    url: str = "",
    *,
    client: httpx.Client | None = None,
) -> Paper:
    """Fetch metadata for a paper. Returns an empty Paper if nothing is found.

    Pass a shared `client` when resolving many papers to reuse connections.
    """
    if client is None:
        with build_http_client() as owned_client:
            return fetch_paper_metadata(doi, url, client=owned_client)

    doi = normalize_doi(doi or extract_doi(url) or "")
    paper = _query_identifier_sources(client, doi, url)
    page_url = url or _arxiv_abstract_url(doi)
    if (paper is None or not paper.title) and page_url:
        page = _ask(lambda: web_page_source.fetch_paper(client, page_url, doi))
        paper = _fill_gaps(paper, page)

    if paper is None:
        return Paper.empty(doi)
    paper.doi = doi or paper.doi
    paper.journal = canonical_journal_name(paper.journal)
    return paper


def _query_identifier_sources(client: httpx.Client, doi: str, url: str) -> Paper | None:
    paper = None
    for lookup in _build_lookups(client, doi, url):
        paper = _fill_gaps(paper, _ask(lookup))
        if paper is not None and not paper.missing_metadata():
            break
    return paper


def _ask(lookup: Lookup) -> Paper | None:
    """Run one source; if it fails, the others are still asked."""
    try:
        return lookup()
    except Exception as error:
        logger.warning("A metadata source failed: %s", error)
        return None


def _build_lookups(client: httpx.Client, doi: str, url: str) -> list[Lookup]:
    lookups: list[Lookup] = []
    arxiv_id = _arxiv_id_for(doi, url)

    if doi and not is_arxiv_doi(doi):  # arXiv preprints are not indexed by PubMed
        lookups.append(lambda: pubmed_source.fetch_by_doi(client, doi))
    if arxiv_id:
        lookups.append(lambda: arxiv_source.fetch_by_id(arxiv_id))
    if doi:
        lookups.append(lambda: crossref_source.fetch_by_doi(client, doi))
    if is_biorxiv_doi(doi):
        lookups.append(lambda: biorxiv_source.fetch_by_doi(client, doi))
    return lookups


def _arxiv_abstract_url(doi: str) -> str:
    """The arXiv abstract page for an arXiv DOI, so the page scrape can back up
    the API; empty for any other DOI."""
    arxiv_id = find_arxiv_id(doi) if is_arxiv_doi(doi) else None
    return f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""


def _arxiv_id_for(doi: str, url: str) -> str | None:
    if is_arxiv_doi(doi):
        return find_arxiv_id(doi)
    if "arxiv.org" in url:
        return find_arxiv_id(url)
    return None


def _fill_gaps(primary: Paper | None, fallback: Paper | None) -> Paper | None:
    """Keep `primary`'s fields; take `fallback`'s only where primary is empty."""
    if primary is None or fallback is None:
        return primary or fallback
    gaps = {
        name: getattr(fallback, name)
        for name in primary.missing_metadata()
        if getattr(fallback, name)
    }
    return replace(primary, **gaps)
