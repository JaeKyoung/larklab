import httpx

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
