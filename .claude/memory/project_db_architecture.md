---
name: Database architecture decisions
description: Key design decisions for paper DB — embedding model, MRL, scoring vs filtering, single table
type: project
---

- Embedding model: `qwen3-embedding:8b` (fixed, no model selection option)
- MRL truncation: 4096 → 1024 dimensions (L2 normalized) — saves 4x storage, negligible quality loss
- DB: single `papers` table + `papers_vec` virtual table (sqlite-vec, cosine distance)
- Scholar digest: **scoring only** (top 3 related papers shown), no filtering — user sees all papers
- Filtering reserved for future crawling feature (arxiv/bioarxiv direct fetch)
- CLI commands all `db-*` prefixed: db-add, db-edit, db-delete, db-list, db-search, db-export, db-import, db-rebuild
- `db-add` accepts URL or DOI and requires a DOI to save. Lookup (`sources/papers/metadata_lookup.fetch_paper_metadata`): PubMed (DOI) → arXiv → CrossRef → bioRxiv API; later sources only fill empty fields; web page only if no title found. CrossRef precedes bioRxiv because the bioRxiv API truncated an author list (45 of 61)
- DB stores DOI only (no URL column); URL derived as `https://doi.org/{doi}` at read time
- `db-add` shows preview before saving, detects near-duplicates (cosine distance < 0.2) with interactive update/new/skip per match
- `db-export` writes individual JSONs to `data/jsons/{id}.json`, `--md` for papers.md (title + URL + DOI)
- `db-import --md` reads papers.md, refetches metadata via DOI/URL, rebuilds DB
- `db-check --refetch` re-fetches from sources and compares with DB (raw comparison, no normalization)
- Digest papers sorted by top-1 reference paper (related papers adjacent)
- Authors separator in CLI: pipe (`|`) not comma (shell-safe)
- Dataclasses in `models.py`: `ScholarPaper` (digest, DOI optional), `Paper` (DB, DOI required; `Paper.url` is a property derived from DOI; `Paper.empty()` placeholder), `Recommendation`/`RecommendationResult`, `DailyDigest`. `ScholarPaper.to_paper()` was removed (unused).
- Digest abstract fetching (`processing/abstract_enricher.enrich_abstracts`): PubMed DOI → PubMed title → CrossRef DOI → web page. `extract_doi()` (in `utils/identifiers.py`) synthesizes arXiv DOI from abs/pdf URL and strips bioRxiv version suffixes.
- bioRxiv DOI prefixes: `10.1101/` and (since 2026) `10.64898/` — kept in `utils/identifiers.BIORXIV_DOI_PREFIXES`
- Sources live one per module in `sources/papers/` (`pubmed_`, `crossref_`, `arxiv_`, `biorxiv_`, `web_page_source.py`); `utils/text.py` has `normalize_title`, `canonical_journal_name` (preprint servers → bioRxiv/medRxiv/arXiv)
- Recommend excludes papers already in the library by DOI or normalized title
- Slack failures are not losses: `send_recommendations_to_slack` returns the undelivered recommendations; `cli/recommend` saves them to `data/outbox.json` (pending first, then progress), posts them with the next run even if nothing new was found, and deletes them once accepted (entries older than 14 days dropped). A crawl that could not read everything (`CrawlResult.complete` False) leaves that source's progress mark where it was. Tests and dev runs must never post to Slack (fakes or `--no-slack`).
- Recommend resumes per source from `data/crawl_progress.json` (written atomically, advanced only after Slack delivery). arXiv lists papers only after announcement (Sun-Thu 20:00 ET), so the old fixed "yesterday" window always returned 0 arXiv papers
- Science journal: CrossRef returns editor summary, PubMed fallback gets real abstract
- Nature: `#Abs1-content` parser with `<sup>` footnote removal
- bioRxiv: API returns SCPLOW markers + trailing footnotes, both auto-cleaned
- PaperRepository is a context manager; every write is one transaction. `replace_all` (import) and `replace_all_embeddings` (rebuild) swap atomically, so compute embeddings first. IDs are plain AUTOINCREMENT (gap-filling removed); `replace_all` restarts ids at 1. `ids_without_embedding()` backs the `db-check` embedding report.

**Why:** User wants to see all Scholar alert papers (never miss any), with similarity as informational context. Filtering will only apply to high-volume crawled sources.
**How to apply:** Don't add filtering to the Scholar digest pipeline. When implementing crawlers, use threshold-based filtering (like prior bot's `any > 0.8` pattern).
