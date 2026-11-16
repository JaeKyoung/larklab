"""CrossRef REST API: look up a paper by DOI."""

import logging
import re

import httpx

from larklab.models import Paper
from larklab.utils.text import collapse_whitespace

logger = logging.getLogger(__name__)

_WORKS_URL = "https://api.crossref.org/works"


def fetch_by_doi(client: httpx.Client, doi: str) -> Paper | None:
    """Return CrossRef metadata for a DOI, or None if CrossRef lacks it."""
    try:
        response = client.get(
            f"{_WORKS_URL}/{doi}", headers={"Accept": "application/json"}
        )
        if response.status_code != 200:
            logger.debug("CrossRef returned %d for %s", response.status_code, doi)
            return None
        message = response.json()["message"]
    except (httpx.HTTPError, KeyError, ValueError) as error:
        logger.debug("CrossRef lookup failed for %s: %s", doi, error)
        return None

    title = _first(message.get("title"))
    if not title:
        return None
    return Paper(
        title=title,
        authors=_parse_authors(message.get("author", [])),
        journal=_first(message.get("container-title")) or _institution_name(message),
        abstract=_clean_abstract(message.get("abstract", "")),
        doi=doi,
    )


def _first(values: list[str] | None) -> str:
    return values[0] if values else ""


def _institution_name(message: dict) -> str:
    """Preprints have no container title; the posting server is the institution."""
    institutions = message.get("institution") or []
    return institutions[0].get("name", "") if institutions else ""


def _parse_authors(authors: list[dict]) -> list[str]:
    names = []
    for author in authors:
        family, given = author.get("family", ""), author.get("given", "")
        name = f"{family}, {given}".strip(", ") or author.get("name", "")
        if name:
            names.append(name)
    return names


def _clean_abstract(raw: str) -> str:
    """Strip JATS markup, a leading 'Abstract' label and trailing section tags."""
    # Drop a JATS "Abstract" heading before the tags go: once the tags are gone it
    # sits flush against the first word ("AbstractWe study ...").
    text = re.sub(
        r"<jats:title[^>]*>\s*Abstract\s*</jats:title>", "", raw, flags=re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^\s*Abstract\b[:.]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*—[A-Z]{1,4}\s*$", "", text)
    return collapse_whitespace(text)
