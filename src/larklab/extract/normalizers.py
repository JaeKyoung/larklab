"""Text normalizers for paper metadata."""

import re


def clean_biorxiv_abstract(raw: str) -> str:
    """Clean bioRxiv abstract: strip SCPLOW markup and trailing digits."""
    text = re.sub(r"[A-Z]+_SCPLOW[A-Z]*C_SCPLOW", "", raw)
    text = re.sub(r"\d+$", "", text)
    return text.strip()


def clean_crossref_abstract(raw: str) -> str:
    """Clean CrossRef abstract: strip HTML tags, 'Abstract' prefix, whitespace."""
    text = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"^\s*Abstract\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*—[A-Z]{1,4}\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
