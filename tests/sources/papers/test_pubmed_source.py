import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from larklab.sources.papers import pubmed_source

ARTICLE_XML = """
<PubmedArticleSet><PubmedArticle>
  <MedlineCitation><Article>
    <Journal><Title>Cell Systems</Title></Journal>
    <ArticleTitle>A study of proteins.</ArticleTitle>
    <Abstract>
      <AbstractText Label="BACKGROUND">Background text.</AbstractText>
      <AbstractText Label="RESULTS">Results text.</AbstractText>
    </Abstract>
    <AuthorList>
      <Author><LastName>Doe</LastName><ForeName>Jane</ForeName></Author>
      <Author><CollectiveName>Some Consortium</CollectiveName></Author>
      <Author><LastName>Roe</LastName></Author>
    </AuthorList>
  </Article></MedlineCitation>
  <PubmedData><ArticleIdList>
    <ArticleId IdType="doi">10.1016/j.cels.2024.01.001</ArticleId>
  </ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>
"""


def _healthy_pubmed(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("esearch.fcgi"):
        return httpx.Response(200, json={"esearchresult": {"idlist": ["42"]}})
    return httpx.Response(200, text=ARTICLE_XML)


def test_fetch_by_doi_parses_structured_abstract_and_authors(http_client):
    paper = pubmed_source.fetch_by_doi(http_client(_healthy_pubmed), "10.1/queried")

    assert paper.title == "A study of proteins."
    assert paper.journal == "Cell Systems"
    assert paper.authors == ["Doe, Jane", "Roe"]  # collective authors are skipped
    assert paper.abstract == "Background text. Results text."  # every section kept
    assert paper.doi == "10.1/queried"


def test_translated_and_plain_language_abstracts_are_not_appended(http_client):
    xml = ARTICLE_XML.replace(
        "</Abstract>",
        "</Abstract><OtherAbstract Language='spa'>"
        "<AbstractText>Resumen en espanol.</AbstractText></OtherAbstract>",
    )

    def handler(request):
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["42"]}})
        return httpx.Response(200, text=xml)

    paper = pubmed_source.fetch_by_doi(http_client(handler), "10.1/x")

    assert paper.abstract == "Background text. Results text."


def test_fetch_by_title_reports_the_dois_pubmed_knows(http_client):
    paper = pubmed_source.fetch_by_title(http_client(_healthy_pubmed), "A study")
    assert paper.doi == "10.1016/j.cels.2024.01.001"


def test_returns_none_when_search_finds_nothing(http_client):
    def handler(request):
        return httpx.Response(200, json={"esearchresult": {"idlist": []}})

    assert pubmed_source.fetch_by_doi(http_client(handler), "10.1/none") is None


def test_retries_after_rate_limit(http_client):
    calls = {"esearch": 0}

    def handler(request):
        if request.url.path.endswith("esearch.fcgi"):
            calls["esearch"] += 1
            if calls["esearch"] == 1:
                return httpx.Response(429)
        return _healthy_pubmed(request)

    paper = pubmed_source.fetch_by_doi(http_client(handler), "10.1/x")

    assert paper is not None
    assert calls["esearch"] == 2


def test_gives_up_after_repeated_server_errors(http_client):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    assert pubmed_source.fetch_by_doi(http_client(handler), "10.1/x") is None
    assert len(calls) == 3


# --- crawling a day's papers ----------------------------------------------------

YESTERDAY = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)


def _midnight(day) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _article(
    pmid,
    title="A Paper",
    *,
    doi="10.1/x",
    abstract="Abstract.",
    journal="Cell Systems",
    short="Cell Syst",
    reference_doi=None,
):
    abstract_xml = f"<Abstract><AbstractText>{abstract}</AbstractText></Abstract>"
    doi_xml = f'<ArticleId IdType="doi">{doi}</ArticleId>' if doi else ""
    references = (
        "<ReferenceList><Reference><ArticleIdList>"
        f'<ArticleId IdType="doi">{reference_doi}</ArticleId>'
        "</ArticleIdList></Reference></ReferenceList>"
        if reference_doi
        else ""
    )
    return (
        f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>"
        f"<Journal><Title>{journal}</Title><ISOAbbreviation>{short}"
        f"</ISOAbbreviation></Journal><ArticleTitle>{title}</ArticleTitle>"
        f"{abstract_xml if abstract else ''}</Article></MedlineCitation>"
        f"<PubmedData><ArticleIdList>{doi_xml}</ArticleIdList>{references}"
        "</PubmedData></PubmedArticle>"
    )


class FakePubMed:
    """Serves the given articles per day, and answers journal-name checks from
    `readings` (the term as sent -> how PubMed read it). Without `readings` every
    exact (quoted) name is known."""

    def __init__(self, days, failing=(), readings=None):
        self.terms, self.checked, self.fetched = [], [], []
        self._failing = {day.strftime("%Y/%m/%d") for day in failing}
        self._readings = readings
        self._ids, self._articles = {}, {}
        for day, articles in days.items():
            stamp = day.strftime("%Y/%m/%d")
            self._ids[stamp] = [f"{day:%m%d}{n}" for n in range(len(articles))]
            self._articles.update(zip(self._ids[stamp], articles, strict=True))

    def handler(self, request):
        params = request.url.params
        if request.url.path.endswith("esearch.fcgi"):
            return self._esearch(params)
        wanted = params["id"].split(",")
        self.fetched.append(wanted)
        body = "".join(self._articles[i] for i in wanted)
        return httpx.Response(200, text=f"<PubmedArticleSet>{body}</PubmedArticleSet>")

    def _esearch(self, params):
        term = params["term"]
        day = re.search(r'"(\d{4}/\d{2}/\d{2})"\[edat\]', term)
        if day is None:  # a journal check
            self.checked.append(term)
            exact = self._readings is None and term.startswith('"')
            reading = term if exact else (self._readings or {}).get(term)
            result = {
                "count": "1" if reading else "0",
                "idlist": [],
                "querytranslation": reading or "",
            }
            return httpx.Response(200, json={"esearchresult": result})
        self.terms.append(term)
        if day.group(1) in self._failing:
            return httpx.Response(500)
        ids = self._ids.get(day.group(1), [])
        result = {"count": str(len(ids)), "idlist": ids[: int(params["retmax"])]}
        return httpx.Response(200, json={"esearchresult": result})

    def days_asked(self):
        return [re.search(r'"(\d{4}/\d{2}/\d{2})"', t).group(1) for t in self.terms]


@pytest.fixture
def pubmed(monkeypatch, http_client):
    def serve(days, **options) -> FakePubMed:
        fake = FakePubMed(days, **options)
        monkeypatch.setattr(
            pubmed_source,
            "build_http_client",
            lambda timeout=None: http_client(fake.handler),
        )
        return fake

    return serve


def test_a_crawl_returns_yesterdays_usable_papers_with_their_journal_as_source(pubmed):
    fake = pubmed(
        {
            YESTERDAY: [
                _article(1, "Complete"),
                _article(2, "No abstract", abstract=""),
                _article(3, "No DOI", doi=""),
            ]
        }
    )

    crawl = pubmed_source.crawl_recent()

    [paper] = crawl.papers
    assert (paper.title, paper.doi) == ("Complete", "10.1/x")
    assert paper.source == "pubmed:Cell Syst"
    assert paper.journal == "Cell Systems"  # the card shows the full name
    assert paper.published_at == datetime(
        YESTERDAY.year, YESTERDAY.month, YESTERDAY.day, tzinfo=UTC
    )
    assert crawl.complete is True
    assert fake.days_asked() == [YESTERDAY.strftime("%Y/%m/%d")]
    assert fake.terms[0].startswith("hasabstract AND ")
    assert fake.terms[0].endswith(
        " NOT preprint[pt]"
    )  # preprints have their own sources


def test_a_reference_lists_doi_is_never_taken_for_the_articles_own(pubmed):
    pubmed({YESTERDAY: [_article(1, doi="", reference_doi="10.9/cited")]})

    assert pubmed_source.crawl_recent().papers == []


def test_preprint_servers_get_the_same_spelling_as_in_the_other_sources(pubmed):
    pubmed(
        {
            YESTERDAY: [
                _article(
                    1,
                    journal="bioRxiv : the preprint server for biology",
                    short="bioRxiv",
                )
            ]
        }
    )

    [paper] = pubmed_source.crawl_recent().papers

    assert paper.journal == "bioRxiv"


def test_journals_narrow_the_search_and_quotes_in_names_are_dropped(pubmed):
    fake = pubmed({YESTERDAY: []})

    pubmed_source.crawl_recent(["Bioinformatics", 'Chem "Sci'])

    assert fake.terms[0].endswith('AND ("Bioinformatics"[jour] OR "Chem Sci"[jour])')
    assert "preprint" not in fake.terms[0]  # a named journal is read as asked


def test_a_journal_pubmed_does_not_know_is_warned_about(pubmed, caplog):
    """A typo in a cron line would otherwise match nothing, silently, every day."""
    fake = pubmed(
        {YESTERDAY: []},
        readings={'"Bioinformatics"[jour]': '"bioinformatics"[Journal]'},
    )

    with caplog.at_level("WARNING"):
        pubmed_source.crawl_recent(["Bioinformatics", "Bioinformatcs"])

    assert "no journal called 'Bioinformatcs'" in caplog.text
    assert "'Bioinformatics'" not in caplog.text
    assert fake.terms[0].endswith(
        'AND ("Bioinformatics"[jour])'
    )  # the typo is left out


def test_a_name_that_is_not_exact_is_handed_to_pubmed_to_map(pubmed, caplog):
    """ "Protein science" is not PubMed's title or abbreviation, but PubMed knows it."""
    fake = pubmed(
        {YESTERDAY: [_article(1, short="Protein Sci", journal="Protein science")]},
        readings={
            '"Bioinformatics"[jour]': '"bioinformatics"[Journal]',
            "Protein science[jour]": '"protein sci"[Journal]',
        },
    )

    with caplog.at_level("INFO"):
        crawl = pubmed_source.crawl_recent(["Protein science", "Bioinformatics"])

    assert fake.terms[0].endswith(
        'AND (Protein science[jour] OR "Bioinformatics"[jour])'
    )
    assert "PubMed reads 'Protein science' as \"protein sci\"[Journal]" in caplog.text
    assert [p.source for p in crawl.papers] == ["pubmed:Protein Sci"]


def test_journals_that_pubmed_cannot_place_never_turn_into_a_crawl_of_everything(
    pubmed,
):
    fake = pubmed({YESTERDAY: [_article(1)]}, readings={})

    crawl = pubmed_source.crawl_recent(["Nonexistent Journal"])

    assert crawl.papers == []
    assert fake.terms == []  # not a single day was searched


def test_without_journals_nothing_is_checked_or_warned_about(pubmed, caplog):
    fake = pubmed({YESTERDAY: []})

    with caplog.at_level("WARNING"):
        pubmed_source.crawl_recent()

    assert fake.checked == []
    assert caplog.text == ""


def test_a_busy_day_is_fetched_in_batches_of_records(pubmed, monkeypatch):
    monkeypatch.setattr(pubmed_source, "_FETCH_BATCH_SIZE", 2)
    fake = pubmed(
        {YESTERDAY: [_article(n, f"Paper {n}", doi=f"10.1/{n}") for n in range(5)]}
    )

    crawl = pubmed_source.crawl_recent()

    assert [p.title for p in crawl.papers] == [f"Paper {n}" for n in range(5)]
    assert [len(ids) for ids in fake.fetched] == [2, 2, 1]


def test_a_day_with_more_papers_than_one_search_can_return_says_how_many_are_skipped(
    pubmed, monkeypatch, caplog
):
    """A search returns 10000 at most. The rest is skipped aloud, and the crawl still
    moves past the day: stopping there would keep it from ever getting further."""
    monkeypatch.setattr(pubmed_source, "_MAX_IDS", 2)
    pubmed({YESTERDAY: [_article(n, f"Paper {n}", doi=f"10.1/{n}") for n in range(3)]})

    with caplog.at_level("WARNING"):
        crawl = pubmed_source.crawl_recent()

    assert len(crawl.papers) == 2
    assert "only the first 2 can be read; the other 1 are skipped" in caplog.text
    assert crawl.read_until is not None


def test_a_crawl_resumes_the_day_after_the_last_one_handled(pubmed):
    fake = pubmed({})
    since = datetime.combine(YESTERDAY - timedelta(days=2), datetime.min.time(), UTC)

    assert pubmed_source.crawl_recent(since=since).complete is True

    assert fake.days_asked() == [
        (YESTERDAY - timedelta(days=1)).strftime("%Y/%m/%d"),
        YESTERDAY.strftime("%Y/%m/%d"),
    ]


def test_the_cap_stops_at_a_day_boundary_never_inside_a_day(pubmed):
    day_before = YESTERDAY - timedelta(days=1)
    fake = pubmed(
        {
            day_before: [_article(n, f"Old {n}", doi=f"10.1/o{n}") for n in range(3)],
            YESTERDAY: [_article(n, f"New {n}", doi=f"10.1/n{n}") for n in range(3)],
        }
    )

    crawl = pubmed_source.crawl_recent(days_back=2, max_results=1)

    assert len(crawl.papers) == 3  # the whole first day, although the cap was 1
    assert fake.days_asked() == [day_before.strftime("%Y/%m/%d")]
    assert crawl.complete is True


def test_a_failing_day_keeps_the_days_before_it_and_marks_the_crawl_incomplete(pubmed):
    day_before = YESTERDAY - timedelta(days=1)
    pubmed(
        {
            day_before: [_article(1, "Safe")],
            YESTERDAY: [_article(2, "Lost", doi="10.1/y")],
        },
        failing=[YESTERDAY],
    )

    crawl = pubmed_source.crawl_recent(days_back=2)

    assert [p.title for p in crawl.papers] == ["Safe"]
    assert crawl.complete is False
    # ...and says it read up to the day before the failing one, so that is where the
    # next run resumes: the safe day is not read, embedded and posted again
    assert crawl.read_until == _midnight(day_before)


def test_a_crawl_says_it_read_up_to_the_last_day_read_in_full(pubmed):
    day_before = YESTERDAY - timedelta(days=1)
    pubmed(
        {day_before: [_article(1, "A")], YESTERDAY: [_article(2, "B", doi="10.1/b")]}
    )

    crawl = pubmed_source.crawl_recent(days_back=2)

    assert crawl.complete is True
    assert crawl.read_until == _midnight(YESTERDAY)


def test_a_day_without_papers_still_counts_as_read(pubmed):
    pubmed({})

    assert pubmed_source.crawl_recent().read_until == _midnight(YESTERDAY)


def test_when_the_first_day_fails_nothing_was_read(pubmed):
    pubmed({YESTERDAY: [_article(1, "Lost")]}, failing=[YESTERDAY])

    crawl = pubmed_source.crawl_recent()

    assert crawl.complete is False
    assert crawl.read_until is None


def test_a_paper_listed_on_two_days_is_returned_once(pubmed):
    day_before = YESTERDAY - timedelta(days=1)
    pubmed(
        {
            day_before: [_article(1, "Same Paper")],
            YESTERDAY: [_article(2, "same paper!", doi="10.1/other")],
        }
    )

    assert len(pubmed_source.crawl_recent(days_back=2).papers) == 1
