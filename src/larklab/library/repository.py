"""SQLite + sqlite-vec storage for the reference-paper library."""

import json
import sqlite3
from collections.abc import Iterable
from typing import Self

import sqlite_vec

from larklab.models import Paper

# Matryoshka truncation of the embedding model's native 4096 dimensions; the table
# below is created with it, and the embedder cuts its vectors to it.
EMBED_DIM = 1024
_PAPER_COLUMNS = "(title, authors, journal, abstract, doi)"
_PAPER_PLACEHOLDERS = "(?, ?, ?, ?, ?)"
_DUPLICATE_SIMILARITY = 0.8  # cosine similarity above this = probably the same paper
_DUPLICATE_CANDIDATES = 10


class PaperRepository:
    """Use as a context manager: the schema is created on enter, the connection
    closed on exit. Every write runs in one transaction (all or nothing)."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> Self:
        self._init_schema()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None

    # --- reads -------------------------------------------------------------

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    def get_by_id(self, paper_id: int) -> Paper | None:
        row = self._db.execute(
            "SELECT * FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        return _row_to_paper(row) if row else None

    def get_by_title(self, title: str) -> Paper | None:
        row = self._db.execute(
            "SELECT * FROM papers WHERE title = ?", (title,)
        ).fetchone()
        return _row_to_paper(row) if row else None

    def list_papers(self) -> list[Paper]:
        rows = self._db.execute("SELECT * FROM papers ORDER BY id").fetchall()
        return [_row_to_paper(row) for row in rows]

    def ids_without_embedding(self) -> list[int]:
        """Papers invisible to similarity search because they lack a vector."""
        rows = self._db.execute(
            "SELECT id FROM papers WHERE id NOT IN (SELECT paper_id FROM papers_vec)"
            " ORDER BY id"
        ).fetchall()
        return [row["id"] for row in rows]

    def search_similar(
        self, embedding: list[float], limit: int = 5
    ) -> list[tuple[Paper, float]]:
        """Closest papers as (paper, cosine similarity), most similar first."""
        rows = self._db.execute(
            """SELECT p.*, v.distance
               FROM papers_vec v
               JOIN papers p ON p.id = v.paper_id
               WHERE v.embedding MATCH ?
                 AND k = ?
               ORDER BY v.distance""",
            (json.dumps(embedding), limit),
        ).fetchall()
        return [(_row_to_paper(row), 1 - row["distance"]) for row in rows]

    def find_duplicates(self, paper: Paper) -> list[tuple[Paper, float]]:
        """Existing papers that look like `paper`, as (paper, similarity score).

        An identical title is a certain match; otherwise close embeddings are.
        """
        same_title = self.get_by_title(paper.title)
        if same_title:
            return [(same_title, 1.0)]
        if not paper.embedding:
            return []
        candidates = self.search_similar(paper.embedding, limit=_DUPLICATE_CANDIDATES)
        return [
            (existing, similarity)
            for existing, similarity in candidates
            if similarity > _DUPLICATE_SIMILARITY
        ]

    # --- writes ------------------------------------------------------------

    def add(self, paper: Paper) -> int:
        """Insert a paper (and its embedding, if set). Returns the new id."""
        with self._db:
            return self._insert_paper(paper)

    def update(self, paper_id: int, paper: Paper) -> None:
        """Overwrite metadata; the embedding is replaced only if `paper` has one."""
        with self._db:
            self._db.execute(
                """UPDATE papers
                   SET title = ?, authors = ?, journal = ?, abstract = ?, doi = ?
                   WHERE id = ?""",
                (*_paper_values(paper), paper_id),
            )
            if paper.embedding:
                self._delete_embedding(paper_id)
                self._insert_embedding(paper_id, paper.embedding)

    def delete(self, paper_id: int) -> bool:
        """Delete a paper and its embedding. Returns False if the id is unknown."""
        with self._db:
            self._delete_embedding(paper_id)
            cursor = self._db.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        return cursor.rowcount > 0

    def replace_all(self, papers: Iterable[Paper]) -> int:
        """Swap the whole library for `papers` atomically; ids restart at 1.

        Papers with a duplicate title are skipped. Returns how many were stored.
        """
        stored = 0
        seen_titles: set[str] = set()
        with self._db:
            self._db.execute("DELETE FROM papers_vec")
            self._db.execute("DELETE FROM papers")
            self._db.execute("DELETE FROM sqlite_sequence WHERE name = 'papers'")
            for paper in papers:
                if paper.title in seen_titles:
                    continue
                seen_titles.add(paper.title)
                self._insert_paper(paper)
                stored += 1
        return stored

    def replace_all_embeddings(self, embeddings: dict[int, list[float]]) -> None:
        """Swap every stored vector atomically. Compute `embeddings` first so a
        failure while embedding never leaves the library without vectors."""
        with self._db:
            self._db.execute("DELETE FROM papers_vec")
            for paper_id, embedding in embeddings.items():
                self._insert_embedding(paper_id, embedding)

    # --- internals ---------------------------------------------------------

    @property
    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self._db_path)
            self._connection.enable_load_extension(True)
            sqlite_vec.load(self._connection)
            self._connection.enable_load_extension(False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def _init_schema(self) -> None:
        self._db.executescript(f"""
            CREATE TABLE IF NOT EXISTS papers (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                title    TEXT NOT NULL UNIQUE,
                authors  TEXT NOT NULL,
                journal  TEXT NOT NULL,
                abstract TEXT NOT NULL,
                doi      TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS papers_vec USING vec0 (
                paper_id INTEGER PRIMARY KEY,
                embedding FLOAT[{EMBED_DIM}] distance_metric=cosine
            );
        """)
        self._migrate_legacy_columns()

    def _migrate_legacy_columns(self) -> None:
        """Older databases stored a `url` column instead of `doi`."""
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(papers)")}
        if "doi" not in columns:
            self._db.execute("ALTER TABLE papers ADD COLUMN doi TEXT")
        if "url" in columns:
            self._db.execute("ALTER TABLE papers DROP COLUMN url")

    def _insert_paper(self, paper: Paper) -> int:
        """INSERT the paper and its embedding (if set); call inside a transaction."""
        cursor = self._db.execute(
            f"INSERT INTO papers {_PAPER_COLUMNS} VALUES {_PAPER_PLACEHOLDERS}",
            _paper_values(paper),
        )
        if paper.embedding:
            self._insert_embedding(cursor.lastrowid, paper.embedding)
        return cursor.lastrowid

    def _insert_embedding(self, paper_id: int, embedding: list[float]) -> None:
        self._db.execute(
            "INSERT INTO papers_vec (paper_id, embedding) VALUES (?, ?)",
            (paper_id, json.dumps(embedding)),
        )

    def _delete_embedding(self, paper_id: int) -> None:
        self._db.execute("DELETE FROM papers_vec WHERE paper_id = ?", (paper_id,))


def _paper_values(paper: Paper) -> tuple:
    return (
        paper.title,
        json.dumps(paper.authors),
        paper.journal,
        paper.abstract,
        paper.doi,
    )


def _row_to_paper(row: sqlite3.Row) -> Paper:
    return Paper(
        id=row["id"],
        title=row["title"],
        authors=json.loads(row["authors"]),
        journal=row["journal"],
        abstract=row["abstract"],
        doi=row["doi"] or "",
    )
