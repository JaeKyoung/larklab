"""db-export and db-import."""

import json

from larklab.cli.library import backup
from larklab.cli.library.backup import (
    export_papers,
    import_papers,
    parse_papers_markdown,
)
from larklab.models import Paper


def test_import_asks_before_replacing_the_library(
    run, repository, make_paper, tmp_path
):
    repository.add(make_paper("Existing"))
    source = tmp_path / "papers.json"
    source.write_text(
        json.dumps(
            [
                {
                    "title": "Imported",
                    "authors": ["A"],
                    "journal": "J",
                    "abstract": "x",
                    "doi": "10.1/i",
                }
            ]
        )
    )

    declined = run(import_papers, ["--input", str(source)], "n\n")
    assert "Cancelled." in declined.output
    assert [p.title for p in repository.list_papers()] == ["Existing"]

    confirmed = run(import_papers, ["--input", str(source), "--yes"])
    assert "Imported 1 papers." in confirmed.output
    assert [p.title for p in repository.list_papers()] == ["Imported"]


def test_export_markdown_round_trips_through_the_parser(
    run, repository, make_paper, tmp_path
):
    repository.add(make_paper("First", doi="10.1/first"))
    repository.add(make_paper("Second", doi="10.1/second"))
    target = tmp_path / "papers.md"

    run(export_papers, ["--md", "--output", str(target)])

    assert parse_papers_markdown(target.read_text()) == [
        ("First", "https://doi.org/10.1/first", "10.1/first"),
        ("Second", "https://doi.org/10.1/second", "10.1/second"),
    ]


def test_parse_markdown_handles_missing_doi_lines_and_none_markers():
    text = "\n".join(
        [
            "# Reference Papers (3)",
            "",
            "- [With DOI](https://doi.org/10.1/a)",
            "  - DOI: 10.1/a",
            "",
            "- [Marked none](https://example.com/b)",
            "  - DOI: (none)",
            "",
            "- [No DOI line](https://example.com/c)",
        ]
    )

    assert parse_papers_markdown(text) == [
        ("With DOI", "https://doi.org/10.1/a", "10.1/a"),
        ("Marked none", "https://example.com/b", None),
        ("No DOI line", "https://example.com/c", None),
    ]


def test_import_markdown_refetches_each_paper_and_survives_a_failure(
    run, repository, monkeypatch, tmp_path
):
    markdown = tmp_path / "papers.md"
    markdown.write_text(
        "- [Good Paper](https://doi.org/10.1/good)\n  - DOI: 10.1/good\n\n"
        "- [Flaky Paper](https://doi.org/10.1/flaky)\n  - DOI: 10.1/flaky\n"
    )

    def fetch(doi, url, client=None):
        if doi == "10.1/flaky":
            raise RuntimeError("timeout")
        return Paper("Good Paper", ["A"], "Nature", "Abstract.", doi)

    monkeypatch.setattr(backup, "fetch_paper_metadata", fetch)

    result = run(import_papers, ["--md", "--input", str(markdown), "--yes"])

    assert "Imported 2 papers." in result.output
    stored = {p.title: p for p in repository.list_papers()}
    assert stored["Good Paper"].journal == "Nature"
    assert stored["Flaky Paper"].doi == "10.1/flaky"  # title and DOI survive


def test_papers_without_a_doi_survive_a_markdown_round_trip(
    run, repository, make_paper, tmp_path
):
    repository.add(make_paper("Legacy Paper", doi=""))
    target = tmp_path / "papers.md"

    run(export_papers, ["--md", "--output", str(target)])

    assert [e[0] for e in parse_papers_markdown(target.read_text())] == ["Legacy Paper"]
