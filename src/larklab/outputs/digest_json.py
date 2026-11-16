"""Write a digest as JSON for downstream automation (e.g. scheduled agents)."""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from larklab.models import DailyDigest, ScholarPaper
from larklab.utils.files import write_text_atomically


def write_digest_json(
    path: Path,
    digests: list[DailyDigest],
    *,
    num_emails: int,
    num_parsed: int,
) -> None:
    """Write the digest atomically: a crash cannot leave a truncated file for the
    scheduled agent that reads it."""
    payload = {
        "generated_at": datetime.now().isoformat(),
        "num_emails": num_emails,
        "num_parsed": num_parsed,
        "digests": [
            {
                "date": digest.date.isoformat(),
                "papers": [_paper_to_dict(paper) for paper in digest.papers],
            }
            for digest in digests
        ],
    }
    write_text_atomically(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, default=datetime.isoformat),
    )


def _paper_to_dict(paper: ScholarPaper) -> dict:
    data = asdict(paper)
    del data["source_email_id"]  # an internal Gmail id, useless downstream
    return data
