# Command reference

All commands are run as `pixi run <command>` (or `pixi run larklab <command>`). Add `--help` to any command for its options.

## `digest`

Fetch Scholar alert emails, enrich them, and post a digest.

| Option | Default | Meaning |
|--------|---------|---------|
| `--days-back N` | 7 | How far back to search Gmail |
| `--max-results N` | 200 | Maximum emails to fetch |
| `--batches N` | all | Process only the latest N alert batches (emails more than 2 hours apart start a new batch) |
| `--query TEXT` | `from:scholaralerts-noreply@google.com` | Gmail search query |
| `--summary` | off | Summarize abstracts with Ollama |
| `--model TEXT` | `qwen3:8b` | Ollama model for `--summary` |
| `--no-fetch-abstracts` | off | Keep the short email snippets |
| `--channel TEXT` | `journal-club` | Slack channel |
| `--no-slack` | off | Print instead of posting (with `--cleanup`, the print counts as delivered) |
| `--cleanup` | off | Trash processed emails once their digest was delivered. Without it nothing is ever trashed |
| `--verbose` | off | Log each trashed email's subject |
| `--output-json PATH` | none | Also write the digest as JSON for downstream automation |

With `--cleanup`, processed emails are moved to Gmail's trash (recoverable) only after their digest was delivered. That includes an email whose papers were all repeats of papers in other emails; an email with a paper in a digest that failed to post stays in the inbox for the next run.

## `recommend [SOURCE...]`

Crawl recent papers and recommend the ones closest to your library. Name the sources to read, one or more of `arxiv`, `biorxiv`, `pubmed`, in the order you want them (`recommend arxiv biorxiv`). With none, all three are read.

| Option | Default | Meaning |
|--------|---------|---------|
| `-c, --categories TEXT` | per source | Comma-separated categories, or journals for `pubmed` (needs exactly one source) |
| `-d, --days-back N` | 1 | Days to look back on the first run (later runs resume, see below) |
| `-n, --top-n N` | 20 | Number of recommendations |
| `-t, --threshold F` | 0.5 | Minimum similarity to the closest reference paper |
| `--channel TEXT` | `journal-club` | Slack channel |
| `--no-slack` | off | Print only |

Papers already in your library are skipped, matched by DOI or by title ignoring case and punctuation. Default categories are listed in [crawl-categories.md](crawl-categories.md).

### PubMed

- Read one finished day at a time, by the date PubMed added each record (days are US Eastern, so a paper indexed in the evening is not skipped). Only papers with an abstract and a DOI count.
- Without `--categories` that is every journal except preprints: about 3000 to 6000 papers a day, about 1.2 s each to embed, so one run takes one to two hours. Preprints are left out because PubMed adds bioRxiv, medRxiv and arXiv copies weeks late, hundreds in one day, while their own sources deliver them on time.
- Narrow it with journals: `pixi run recommend pubmed -c "Bioinformatics,Chemical Science"`. Journals are separated by commas, so a full name that contains one ("Proteins: Structure, Function, and Bioinformatics") needs its abbreviation (`Proteins`).
- A name may be PubMed's exact title or abbreviation, or any spelling PubMed can map by itself: `Protein science` is read as `Protein Sci`, and the log says so. A name PubMed cannot place is warned about and left out; if none can be placed, nothing is read (never all of PubMed).
- Papers are listed as `pubmed:<journal>` (`pubmed:Chem Sci`); the Slack headline shows only the journals that have a recommendation.
- Everything a run reads is scored before anything is posted, so a slow PubMed run holds back the other sources' posts of the same run. Run PubMed on its own ([scheduling](scheduling.md)) and raise `-t` to keep only the closest papers.

### Resuming and state files

Each paper is recommended once, and none is lost. `recommend` keeps two small files in `data/` (gitignored, safe to delete; their paths are set in `config.py`):

- `crawl_progress.json` — the newest paper handled per source. The next run resumes after it and catches up on missed days (at most a week).
- `outbox.json` — recommendations Slack refused. They are posted with the next run's recommendations (even when that run finds nothing new) and removed once Slack accepts them. Entries older than two weeks are dropped.

The sources differ:

- **arXiv** lists a paper only after it is *announced* (Sunday to Thursday evening, US Eastern), so at breakfast time in Asia the newest paper is one to three days old and a fixed "yesterday" window is always empty. It can also list a paper after newer ones (held for moderation), so it is read two days further back than its mark and the papers of that stretch are remembered, to be recommended only once.
- **bioRxiv** publishes whole days; it resumes at the day after the last one seen.

A source's progress moves forward only when the crawl read everything: if one arXiv category failed (HTTP 429/503), the source is fetched again next time. You may see a few repeats, never a gap. A `--no-slack` run prints the pending and new recommendations and changes nothing.

Per-run limits: arXiv up to 1000 papers per category; PubMed one day at a time, stopping after the day that passes 4000 papers (a catch-up after missed days takes about a day per run); bioRxiv up to 200 matching papers, but never in the middle of a day. The design reasons are in [architecture.md](architecture.md#recommendations-resume-and-nothing-is-lost-on-the-way).

## Library commands

```bash
pixi run db-add <doi-or-url>              # fetch, preview, confirm, embed, save
pixi run db-add <doi> --journal "bioRxiv" # override any fetched field (--title --authors --journal --abstract)
pixi run db-edit <id> --journal "Nature"  # edit fields (also --title --authors --abstract --doi)
pixi run db-delete <id>                   # delete (asks first)
pixi run db-list                          # list everything
pixi run db-search "AlphaFold"            # keyword match in titles + similar papers by embedding
pixi run db-search --journal "Science"    # filter by journal
pixi run db-check                         # missing fields, and papers without an embedding
pixi run db-check --refetch               # also re-fetch every paper and show what changed
pixi run db-export                        # one JSON per paper in data/jsons/
pixi run db-export --md                   # data/papers.md (title + DOI link)
pixi run db-import --md                   # rebuild the library from data/papers.md
pixi run db-import --input file.json -y   # replace from JSON without asking
pixi run db-rebuild                       # re-embed every paper
```

Authors are separated with `|` on the command line (`--authors "Doe, Jane|Roe, Rich"`) because names contain commas.

### How the library behaves

The library is the heart of the scoring, so it is worth knowing how it behaves.

- **A DOI is required.** `db-add` refuses a paper it cannot find a DOI for. Pass a DOI instead of a URL when a page does not expose one. arXiv papers get a synthetic DOI (`10.48550/arXiv.<id>`).
- **Previews first.** `db-add` prints what it found, lists missing fields, and defaults to "No" when anything is missing. Use the override options to fill gaps, then confirm.
- **Near-duplicates are caught.** An identical title, or an embedding closer than cosine distance 0.2, triggers a prompt per match: `update` (same paper, overwrite), `new` (different paper), or `skip`.
- **Journal names are normalized** for preprint servers (`bioRxiv`, `medRxiv`, `arXiv`), because the sources spell them differently.
- **`db-check`** flags papers with missing fields and papers that exist but have no embedding (they would silently never match anything). Fix those with `db-rebuild`.
- **Writes are all-or-nothing.** `db-import` and `db-rebuild` compute everything first and swap it in with one transaction, so a failure (for example Ollama going down) leaves the library as it was.
- **`papers.md` is lossy by design** (titles and DOIs only). `db-import --md` re-fetches everything over the network, so its result can differ slightly from what you had. For a faithful backup use `db-export` (JSON, includes abstracts) or copy `data/larklab.db`.

### Changing the embedding model

The model is fixed on purpose so that every vector in the database is comparable. To switch:

1. `ollama pull <new-model>`
2. Edit `EMBED_MODEL` (and `EMBED_DIM` if the new model's vectors are not truncatable to 1024) in `src/larklab/library/embedder.py`. The table's vector column is created with `EMBED_DIM`, so a different dimension also needs a new database file.
3. `pixi run db-export` to keep a JSON copy, then `pixi run db-rebuild`.
4. Run `pixi run db-check`, then compare a few `db-search` queries against what you saw before.

Mixing vectors from two models in one database gives meaningless similarity scores — always rebuild everything.
