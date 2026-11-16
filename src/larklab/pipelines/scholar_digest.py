"""Digest pipeline: Scholar alert emails → papers → abstracts → summaries → scores.

Pure orchestration with no I/O of its own beyond the collaborators it is given,
so a future interactive bot can call `run_digest_pipeline` directly.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from larklab.library.repository import PaperRepository
from larklab.library.similarity import find_similar_references
from larklab.models import DailyDigest
from larklab.processing.abstract_enricher import enrich_abstracts
from larklab.processing.dedup import dedup_and_group_by_date
from larklab.processing.summarizer import DEFAULT_SUMMARY_MODEL, summarize_abstract
from larklab.sources.gmail.client import GmailClient

logger = logging.getLogger(__name__)

BATCH_GAP_HOURS = 2  # emails further apart than this belong to different alert batches
MAX_SUMMARY_FAILURES_IN_A_ROW = 3

Batch = list[tuple[str, int]]  # [(message id, received time in epoch milliseconds)]


@dataclass(frozen=True)
class DigestOptions:
    query: str
    max_results: int
    days_back: int
    fetch_abstracts: bool = True
    summarize: bool = False
    summary_model: str = DEFAULT_SUMMARY_MODEL
    num_batches: int | None = None  # None = process every batch


@dataclass
class DigestResult:
    digests: list[DailyDigest]
    num_emails: int  # emails read
    num_parsed: int
    # emails that held at least one paper, including ones whose papers all turned
    # out to be repeats of papers in other emails. An email with no paper stays out:
    # it may be an alert layout the parser does not know yet, and trashing it would
    # hide that.
    message_ids: list[str] = field(default_factory=list)


def run_digest_pipeline(
    gmail: GmailClient, db_path: str, options: DigestOptions
) -> DigestResult:
    logger.info("Fetching Scholar emails from the last %d days...", options.days_back)
    message_ids = gmail.list_message_ids(
        options.query, options.max_results, options.days_back
    )
    if not message_ids:
        logger.info("Found 0 emails.")
        return DigestResult(digests=[], num_emails=0, num_parsed=0)

    logger.info("Found %d emails, detecting batches...", len(message_ids))
    batches = group_into_batches(gmail.fetch_message_timestamps(message_ids))
    _log_batches(batches, options.num_batches)
    if options.num_batches is not None:
        batches = batches[: options.num_batches]

    raw_messages = gmail.fetch_full_messages(
        [message_id for batch in batches for message_id, _ in batch]
    )
    logger.info("Processing %d emails.", len(raw_messages))
    papers = gmail.parse_emails(raw_messages)
    logger.info("Parsed %d papers total.", len(papers))

    digests = dedup_and_group_by_date(papers)
    if options.fetch_abstracts:
        for digest in digests:
            logger.info(
                "Fetching full abstracts for %d papers (%s)...",
                len(digest.papers),
                digest.date,
            )
            digest.papers = enrich_abstracts(digest.papers)
    if options.summarize:
        _summarize_papers(digests, options.summary_model)

    _attach_similar_references(digests, db_path)
    for digest in digests:  # related papers end up next to each other
        digest.papers.sort(key=_top_similarity, reverse=True)

    message_ids = sorted({paper.source_email_id for paper in papers})
    if len(message_ids) < len(raw_messages):
        logger.warning(
            "%d email(s) held no papers (a new alert layout?); they stay in the inbox.",
            len(raw_messages) - len(message_ids),
        )
    return DigestResult(
        digests=digests,
        num_emails=len(raw_messages),
        num_parsed=len(papers),
        message_ids=message_ids,
    )


def message_ids_to_trash(result: DigestResult, sent: list[DailyDigest]) -> list[str]:
    """Emails that are safe to trash once `sent` digests were delivered.

    That is every processed email except those with a paper in a digest that was
    not sent. An email whose papers were all dropped as repeats goes too: those
    papers were delivered through another email.
    """
    sent_digests = {id(digest) for digest in sent}
    unsent_email_ids = {
        paper.source_email_id
        for digest in result.digests
        if id(digest) not in sent_digests
        for paper in digest.papers
    }
    return sorted(set(result.message_ids) - unsent_email_ids)


def group_into_batches(timestamps: Batch) -> list[Batch]:
    """Group messages into alert batches by time gap, newest batch first."""
    if not timestamps:
        return []
    gap_ms = BATCH_GAP_HOURS * 3600 * 1000
    ordered = sorted(timestamps, key=lambda message: message[1])
    batches: list[Batch] = [[ordered[0]]]
    for message in ordered[1:]:
        if message[1] - batches[-1][-1][1] > gap_ms:
            batches.append([message])
        else:
            batches[-1].append(message)
    batches.reverse()
    return batches


def _log_batches(batches: list[Batch], num_batches: int | None) -> None:
    descriptions = []
    for number, batch in enumerate(batches, 1):
        newest = max(timestamp for _, timestamp in batch)
        moment = datetime.fromtimestamp(newest / 1000, tz=UTC).astimezone()
        descriptions.append(
            f"Batch {number} ({len(batch)} emails, {moment:%m/%d %H:%M})"
        )
    logger.info("Found %d batches: %s", len(batches), " | ".join(descriptions))
    if num_batches is not None:
        selected_emails = sum(len(batch) for batch in batches[:num_batches])
        logger.info(
            "Processing latest %d batch(es) (%d emails)...",
            num_batches,
            selected_emails,
        )


def _summarize_papers(digests: list[DailyDigest], model: str) -> None:
    """Best effort: a paper that cannot be summarized keeps its abstract in the
    digest. After a few failures in a row Ollama is probably down, so stop instead
    of waiting out a timeout per paper."""
    papers = [paper for digest in digests for paper in digest.papers]
    failures_in_a_row = 0
    for number, paper in enumerate(papers, 1):
        logger.info("  Summarizing paper %d/%d...", number, len(papers))
        try:
            paper.summary = summarize_abstract(paper, model=model)
            failures_in_a_row = 0
        except Exception as error:
            logger.warning("  Could not summarize %r: %s", paper.title, error)
            failures_in_a_row += 1
            if failures_in_a_row == MAX_SUMMARY_FAILURES_IN_A_ROW:
                logger.warning("  Giving up on summaries; the rest keep abstracts.")
                return


def _attach_similar_references(digests: list[DailyDigest], db_path: str) -> None:
    """Score every paper against the reference library (scoring only, no filtering)."""
    papers = [paper for digest in digests for paper in digest.papers]
    with PaperRepository(db_path) as repository:
        if repository.count() == 0:
            logger.info("No reference papers in DB — skipping similarity scoring.")
            return
        if not papers:
            return
        logger.info("Embedding %d papers for similarity scoring...", len(papers))
        similar_lists = find_similar_references(papers, repository)
        for paper, similar in zip(papers, similar_lists, strict=True):
            paper.similar_papers = similar or None


def _top_similarity(paper) -> float:
    return paper.similar_papers[0][1] if paper.similar_papers else 0
