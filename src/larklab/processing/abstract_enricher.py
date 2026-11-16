"""Replace the short snippets in Scholar alerts with full abstracts.

Sources, cheapest first: PubMed by DOI, PubMed by title, CrossRef by DOI, then
the paper's own web page. A fetched abstract only replaces the snippet when it
is longer; on any failure the original paper is kept.
"""

import logging
import time
from dataclasses import replace

import httpx

from larklab.models import Paper, ScholarPaper
from larklab.sources.papers import crossref_source, pubmed_source, web_page_source
from larklab.utils.http import build_http_client
from larklab.utils.identifiers import extract_doi, resolve_paper_url

logger = logging.getLogger(__name__)

_POLITE_DELAY_SECONDS = 2.0


def enrich_abstracts(papers: list[ScholarPaper]) -> list[ScholarPaper]:
    """Return papers with full abstracts (and DOIs) filled in where found."""
    enriched = []
    with build_http_client() as client:
        for paper in papers:
            try:
                enriched.append(_enrich_paper(client, paper))
            except Exception:
                logger.warning(
                    "Failed to fetch abstract for %s, keeping snippet",
                    paper.title,
                    exc_info=True,
                )
                enriched.append(paper)
    return enriched


def _enrich_paper(client: httpx.Client, paper: ScholarPaper) -> ScholarPaper:
    url = resolve_paper_url(paper.url)
    doi = extract_doi(url) if url else None

    def is_longer_than_snippet(abstract: str) -> bool:
        return len(abstract) > len(paper.abstract)

    abstract = ""
    if doi:
        abstract = _abstract_of(pubmed_source.fetch_by_doi(client, doi))
    if not is_longer_than_snippet(abstract):
        by_title = pubmed_source.fetch_by_title(client, paper.title)
        # A title search can hit the wrong record: trust its DOI only when its
        # abstract proved useful.
        if by_title and is_longer_than_snippet(by_title.abstract):
            abstract = by_title.abstract
            doi = doi or by_title.doi or None
    if doi and not is_longer_than_snippet(abstract):
        abstract = _abstract_of(crossref_source.fetch_by_doi(client, doi)) or abstract
    if url and not is_longer_than_snippet(abstract):
        time.sleep(_POLITE_DELAY_SECONDS)  # only publisher pages need the courtesy
        abstract = web_page_source.fetch_abstract(client, url) or abstract

    updates: dict[str, str] = {}
    if is_longer_than_snippet(abstract):
        updates["abstract"] = abstract
    if doi and not paper.doi:
        updates["doi"] = doi
    return replace(paper, **updates) if updates else paper


def _abstract_of(paper: Paper | None) -> str:
    return paper.abstract if paper else ""
