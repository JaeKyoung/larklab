"""Helpers shared by the commands that change a paper (db-add, db-edit)."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

import click

from larklab.models import Paper


def apply_overrides(
    paper: Paper,
    *,
    title: str | None = None,
    authors: str | None = None,
    journal: str | None = None,
    abstract: str | None = None,
    doi: str | None = None,
) -> None:
    """Overwrite the fields the user passed on the command line.

    `authors` is pipe-separated ('A|B') because names contain commas.
    """
    if title:
        paper.title = title
    if authors:
        paper.authors = [name.strip() for name in authors.split("|")]
    if journal:
        paper.journal = journal
    if abstract:
        paper.abstract = abstract
    if doi:
        paper.doi = doi


@contextmanager
def reject_duplicate_titles() -> Iterator[None]:
    """Titles are unique in the library: report a clash as a normal CLI error."""
    try:
        yield
    except sqlite3.IntegrityError as error:
        raise click.ClickException(
            "Another paper in the library already has this title."
        ) from error
