# LarkLab

<p align="center">
  <img src="img/image.png" alt="LarkLab">
</p>

A personal research assistant that collects, organizes, and recommends papers. It runs entirely on your own machine: papers live in a local SQLite file, embeddings and summaries come from a local [Ollama](https://ollama.ai) server, and the only outside services it talks to are Gmail (read + trash), Slack (post), and public paper metadata APIs.

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Setup in detail](#setup-in-detail)
- [Command reference](#command-reference)
- [The reference library](#the-reference-library)
- [Configuration](#configuration)
- [Example output](#example-output)
- [Project layout](#project-layout)
- [Development](#development)
- [Scheduling](#scheduling)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

## What it does

| Feature | Command | In one sentence |
|---------|---------|-----------------|
| Scholar digest | `digest` | Reads your Google Scholar alert emails, fetches full abstracts, optionally summarizes them with a local LLM, scores each paper against your reference library, and posts a threaded digest to Slack. |
| Recommendations | `recommend` | Crawls the arXiv and bioRxiv submissions that are new since the last run, scores them against your reference library, and posts the closest matches to Slack. |
| Reference library | `db-*` | A small curated set of papers you care about, stored with vector embeddings. Everything above is scored against it. |

Nothing is filtered out of the Scholar digest: every paper in your alerts is shown, and similarity to your reference papers is only context. Filtering (a similarity threshold) applies to `recommend`, where the volume is too high to read everything.

## How it works

```
digest     Gmail → batch detection → parse → dedup → full abstracts → summaries → similarity → Slack / JSON
recommend  arXiv + bioRxiv crawl → drop papers you already have → similarity → threshold + top-N → Slack
db-add     DOI or URL → metadata from several sources → preview → embedding → duplicate check → SQLite
```

- **Embeddings**: Ollama `qwen3-embedding:8b`, truncated to 1024 dimensions (Matryoshka) and L2-normalized. The text embedded is `title + "\n" + abstract`. Similarity is cosine (`1 - distance`).
- **Storage**: one SQLite file, `data/larklab.db`, using [sqlite-vec](https://github.com/asg017/sqlite-vec) for vector search. Two tables: `papers` and `papers_vec`.
- **Metadata sources** (`db-add`, `db-check --refetch`, `db-import --md`): PubMed, arXiv, CrossRef and bioRxiv are queried in that order and each later source only fills fields the earlier ones left empty, stopping as soon as title, authors, journal and abstract are all present. A publisher web page is used only if no source found a title.
- **Summaries**: Ollama `qwen3:8b`, three bullets per abstract, only with `--summary`. Thinking mode is switched off (about 3 s per paper instead of 17 s). A paper that cannot be summarized keeps its abstract in the digest, and after three failures in a row (Ollama down) the remaining papers are not tried.
- **Privacy**: no paper text is sent to a hosted LLM. Summaries and embeddings are computed locally.

## Quick start

```bash
# 1. dependencies (pixi installs Python and everything else)
pixi install

# 2. local models
ollama pull qwen3-embedding:8b
ollama pull qwen3:8b            # only needed for `digest --summary`

# 3. credentials: see "Setup in detail" for Gmail and Slack
cp .env.example .env

# 4. seed the reference library with a few papers you like
pixi run db-add 10.1038/s41586-021-03819-2

# 5. try it without posting anywhere
pixi run digest --batches 1 --no-slack
pixi run recommend --no-slack
```

Only the reference library is needed to try `recommend --no-slack`; Gmail and Slack are needed only for `digest` and for posting.

## Setup in detail

### Prerequisites

- Python 3.12+ (managed by [pixi](https://pixi.sh))
- [Ollama](https://ollama.ai) running locally with `qwen3-embedding:8b` (and `qwen3:8b` for summaries)
- For `digest`: a Google Cloud project with the Gmail API enabled, and Google Scholar alerts delivered to that Gmail account
- For Slack posting: a Slack bot token (see [docs/slack-setup.md](docs/slack-setup.md))

### 1. Gmail API credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable the **Gmail API**: **API & Services** → **Library**, search "Gmail API", click **Enable**
4. **API & Services** → **OAuth consent screen**: user type **External**, fill in app name and email, save
5. Add your Gmail address as a **test user**
6. **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**, application type **Desktop application**
7. Download the JSON file and put it where LarkLab expects it (or point `GMAIL_CREDENTIALS_PATH` at it):

```bash
mkdir -p credentials
mv ~/Downloads/client_secret_*.json credentials/credentials.json
```

On the first `digest` run a browser window opens for OAuth consent. LarkLab requests only the `gmail.readonly` and `gmail.modify` scopes (read, and move to trash); the `send` scope is deliberately not requested. The resulting token is saved to `credentials/token.json` with owner-only permissions.

### 2. Environment variables

```bash
cp .env.example .env
```

Edit `.env` and add your Slack bot token:

```
SLACK_BOT_TOKEN=xoxb-your-token-here
```

`.env` holds secrets and file paths only. Every other setting is a command-line option.

### 3. Install and run

```bash
pixi install
pixi run digest
```

## Command reference

All commands are run as `pixi run <command>` (or `pixi run larklab <command>`). Add `--help` to any command for its options.

### `digest`

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

### `recommend [arxiv|biorxiv]`

Crawl recent preprints and recommend the ones closest to your library.

| Option | Default | Meaning |
|--------|---------|---------|
| `-c, --categories TEXT` | per source | Comma-separated categories (requires a source argument) |
| `-d, --days-back N` | 1 | Days to look back on the first run (later runs resume, see below) |
| `-n, --top-n N` | 20 | Number of recommendations |
| `-t, --threshold F` | 0.5 | Minimum similarity to the closest reference paper |
| `--channel TEXT` | `journal-club` | Slack channel |
| `--no-slack` | off | Print only |

Papers already in your library are skipped, matched by DOI or by title ignoring case and punctuation. Default categories are listed in [docs/crawl-categories.md](docs/crawl-categories.md).

**Each paper is recommended once, and none is lost.** `recommend` keeps two small files in `data/` (both gitignored, safe to delete):

- `crawl_progress.json` — the newest paper handled per source. The next run resumes after it and catches up on missed days (at most a week). This matters because the servers behave differently: **arXiv** lists a paper only after it is *announced* (Sunday to Thursday evening, US Eastern), so at breakfast time in Asia the newest paper is one to three days old and a fixed "yesterday" window is always empty — which is why arXiv never showed up before. **bioRxiv** publishes whole days, so it resumes at the day after the last one seen.
- `outbox.json` — recommendations Slack refused. They are kept and posted together with the next run's recommendations (even when that run finds nothing new), and removed as soon as Slack accepts them. Papers older than two weeks are dropped.

A source's progress moves forward only when the crawl read everything. If one arXiv category failed (HTTP 429/503), the source is fetched again next time: you may see a few repeats, but never a gap. A `--no-slack` run prints the pending and new recommendations and changes nothing. arXiv is read up to 1000 papers per category per run, which covers a busy announcement of cs.LG. bioRxiv is read up to 200 matching papers per run, but never stops in the middle of a day (the next run resumes on the day after); its API now returns 30 entries per page, so the crawl follows the page size it is given.
### Library commands

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

## The reference library

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

## Configuration

Secrets and paths live in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_CREDENTIALS_PATH` | `credentials/credentials.json` | OAuth client credentials |
| `GMAIL_TOKEN_PATH` | `credentials/token.json` | Where the OAuth token is stored |
| `SLACK_BOT_TOKEN` | | Slack bot user OAuth token ([setup](docs/slack-setup.md)) |

The database is always `data/larklab.db` (gitignored). `credentials/` and `.env` are gitignored; never commit them.

## Example output

### Terminal

```
Fetching Scholar emails from the last 7 days...
Found 10 emails, detecting batches...
Found 2 batches: Batch 1 (6 emails, 03/19 07:16) | Batch 2 (4 emails, 03/17 08:30)
Processing 10 emails.
Parsed 25 papers total.

============================================================
  Google Scholar Digest — 25 papers, 2 days
============================================================

--- 2026-03-18 (15 papers) ---

  1. Paper Title Here
     Authors: A Author, B Author
     Journal: Nature, 2026
     Abstract: Lorem ipsum dolor sit amet...
     URL: https://doi.org/10.1234/example
     Top 1 related paper (similarity: 0.823)
     Reference Paper Alpha
     Top 2 related paper (similarity: 0.756)
     Reference Paper Beta
     Top 3 related paper (similarity: 0.691)
     Reference Paper Gamma

  ...

Sent 2 batch(es) to #journal-club (25 papers total)
Trashed 10 processed emails.
```

### Slack

Each batch is a headline message with one threaded card per paper:

```
*Scholar Digest — 2026-03-18*
• 15 papers
  ┃ Nature, 2026
  ┃ Paper Title Here
  ┃ Lorem ipsum dolor sit amet, consectetur adipiscing elit...
  ┃ Authors: A Author, B Author
  ┃ Top 1 related paper (similarity: 0.823): Reference Paper Alpha
  ┃ Top 2 related paper (similarity: 0.756): Reference Paper Beta
  ┃ Top 3 related paper (similarity: 0.691): Reference Paper Gamma
```

`recommend` posts one thread per publication date, with a headline such as `• arxiv: 3/40` (recommended / candidates scored).

### `--output-json`

`digest --output-json out.json` writes everything a downstream script needs:

```json
{
  "generated_at": "2026-03-19T08:00:12",
  "num_emails": 10,
  "num_parsed": 25,
  "digests": [
    {
      "date": "2026-03-18",
      "papers": [
        {
          "title": "Paper Title Here",
          "authors": ["A Author", "B Author"],
          "journal": "Nature, 2026",
          "abstract": "Lorem ipsum...",
          "url": "https://doi.org/10.1234/example",
          "received_at": "2026-03-18T07:16:00+00:00",
          "summary": "",
          "doi": "10.1234/example",
          "similar_papers": [["Reference Paper Alpha", 0.823]]
        }
      ]
    }
  ]
}
```

## Project layout

Folder names say what the code does; each folder holds one kind of thing.

```
src/larklab/
├── main.py                      entry point
├── config.py                    secrets and paths from .env
├── models.py                    dataclasses: Paper, ScholarPaper, Recommendation, DailyDigest
│
├── cli/                         what you can run — thin: parse options, call a pipeline, print
│   ├── digest.py                digest
│   ├── recommend.py             recommend
│   └── library/                 one module per job
│       ├── add.py               db-add
│       ├── edit.py              db-edit, db-delete
│       ├── browse.py            db-list, db-search
│       ├── health.py            db-check, db-rebuild
│       └── backup.py            db-export, db-import
│
├── pipelines/                   end-to-end flows; no printing, reusable by a future bot
│   ├── scholar_digest.py        Gmail → papers → abstracts → summaries → scores
│   ├── paper_recommendations.py crawl → exclude known → score → rank
│   ├── crawl_progress.py        remembers how far each source was crawled
│   └── outbox.py                keeps recommendations Slack refused until they are sent
│
├── sources/                     reading from outside systems
│   ├── gmail/                   client.py (OAuth, fetch, trash), scholar_alert_parser.py
│   └── papers/                  pubmed_, crossref_, arxiv_, biorxiv_, web_page_source.py,
│                                and metadata_lookup.py which merges them: DOI/URL → one Paper
│
├── processing/                  improving the fetched papers
│   ├── abstract_enricher.py     email snippet → full abstract
│   ├── dedup.py                 drop repeats, group by day
│   └── summarizer.py            three-bullet summaries (Ollama)
│
├── library/                     the reference library
│   ├── repository.py            SQLite + sqlite-vec
│   ├── embedder.py              Ollama embeddings
│   └── similarity.py            closest reference papers for each paper
│
├── outputs/                     sending results somewhere
│   ├── slack/                   paper_thread.py, digest.py, recommendations.py
│   ├── terminal.py              console output
│   └── digest_json.py           --output-json
│
└── utils/                       small helpers that know nothing about the project
    ├── identifiers.py           DOI / arXiv ID / URL helpers
    ├── text.py                  title matching, journal names
    ├── http.py                  the shared HTTP client
    └── files.py                 atomic file writes

tests/                           mirrors src/larklab/ folder by folder (offline)
scripts/manual/                  hand-run helpers that touch live Gmail / Slack
```

Dependencies only point downward: `cli → pipelines → sources / processing / library → models`. `outputs` depends on `models` alone, `utils` on nothing in the project, and there are no import cycles. See [docs/architecture.md](docs/architecture.md) for the diagram and design notes.

## Development

After cloning:

```bash
pixi install
pixi run pre-commit install
```

The hooks run ruff (lint + format) and re-export `data/papers.md` from the database on every commit.

```bash
pixi run test      # offline test suite — no network, no Ollama, no Gmail, no Slack
pixi run lint      # ruff check
pixi run format    # ruff format
```

The tests mirror the source tree (`tests/sources/papers/test_pubmed_source.py` tests `src/larklab/sources/papers/pubmed_source.py`). They use fake sources and a temporary SQLite file, so they are safe to run anywhere. Scripts that touch live services (Gmail, Slack) are not tests; they live in `scripts/manual/` and are run by hand.

Conventions are in [CLAUDE.md](CLAUDE.md): commit messages follow `.github/git_commit_template.md`, all code and docs are in English, and dependencies are added with `pixi add`.

### Adding a metadata source

1. Create `sources/papers/<name>_source.py` exposing `fetch_by_doi(client, doi) -> Paper | None` (return `None` rather than an empty `Paper` when the source does not know the paper).
2. Register it in `_build_lookups` in `sources/papers/metadata_lookup.py` at the right priority.
3. Test it with `httpx.MockTransport` (see `tests/test_crossref_source.py`).

## Scheduling

### Option 1: cron

```bash
crontab -e
```

```bash
# Digest at 8:00 AM
0 8 * * * cd /path/to/larklab && /path/to/pixi run digest --days-back 999 --max-results 200 --batches 5 --cleanup >> /tmp/larklab.log 2>&1
# Recommend at 11:00 AM, after arXiv's morning announcement (see Timing below)
0 11 * * * cd /path/to/larklab && /path/to/pixi run recommend >> /tmp/larklab.log 2>&1
```

Progress is logged to stdout, so `/tmp/larklab.log` shows each stage. Check registration with `crontab -l`.

> **macOS**: you may need to grant **Full Disk Access** to `cron` (or your terminal) in **System Settings → Privacy & Security** for the Gmail token to be readable.

> **Warning**: cron skips jobs when the machine is asleep or off and does not retry. Use launchd if you want missed jobs to run on wake.

> **Tip**: cron runs whatever branch is checked out in the project directory. Keep that checkout on a stable branch and develop in a separate `git worktree`.

> **Timing**: arXiv announces new papers around 20:00 US Eastern, which is 09:00 in Korea during US daylight time and 10:00 otherwise. `recommend` resumes from `data/crawl_progress.json`, so no paper is missed whatever the hour — but run it at 11:00 or later so that morning's announcement is already listed; a 09:00 run would only see it a day later. A digest run without `--summary` (the example above) does not use the Ollama chat model at all; only the embedding model is needed.

### Option 2: launchd (recommended for macOS)

launchd runs missed jobs when the machine wakes up.

1. Remove the cron job if present (`crontab -e`).
2. Create the plist, replacing the paths. For `recommend`, make a second copy with the label `com.larklab.recommend`, the argument `recommend` and `Hour` 11 (see the timing note above):

```bash
cat > ~/Library/LaunchAgents/com.larklab.digest.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.larklab.digest</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/pixi</string>
        <string>run</string>
        <string>digest</string>
        <string>--cleanup</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/larklab</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/larklab.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/larklab.log</string>
</dict>
</plist>
EOF
```

3. Load it and check:

```bash
launchctl load ~/Library/LaunchAgents/com.larklab.digest.plist
launchctl list | grep larklab
```

To disable:

```bash
launchctl unload ~/Library/LaunchAgents/com.larklab.digest.plist
rm ~/Library/LaunchAgents/com.larklab.digest.plist
```

## Troubleshooting

| Symptom | Likely cause and fix |
|---------|----------------------|
| Only bioRxiv papers show up in Slack | arXiv lists a paper only after it is announced, so "yesterday" is always empty. `recommend` now resumes from `data/crawl_progress.json`; check the log for `Found N papers (arxiv: …)`. 429/503 from arXiv are retried per category and logged as `arXiv rate limited` / `arXiv crawl stopped`. |
| `db-check` says `missing: embedding` | The paper was stored without a vector, so similarity search cannot see it. Run `pixi run db-rebuild`. |
| `db-add` ends with "Could not determine a DOI" | The page does not expose a DOI. Find it on the publisher page and pass the DOI instead of the URL. |
| `db-add` shows `Journal: (none)` | The sources did not return a journal. Pass `--journal`. |
| Connection errors from `db-add`, `db-rebuild`, `digest` | Ollama is not running, or the model is not pulled: `ollama serve`, `ollama pull qwen3-embedding:8b`. |
| Slack posts nothing | `SLACK_BOT_TOKEN` is empty, or the bot is not invited to the channel. See [docs/slack-setup.md](docs/slack-setup.md). `digest` then keeps your emails; `recommend` keeps the recommendations in `data/outbox.json` and sends them with the next run. |
| The digest lists papers with short abstracts | Some sites block automated requests. The snippet from the email is kept (see below). |

## Known limitations

- **Abstract coverage**: full abstracts come from PubMed, then CrossRef, then the paper's web page (arXiv, Nature, generic meta tags). Papers not indexed in PubMed and hosted on JavaScript-rendered or bot-protected sites keep the short snippet from the email.
- **Scholar HTML**: the alert parser depends on Google's email layout. If Google changes it, only `sources/gmail/scholar_alert_parser.py` needs to change.
- **Sequential Gmail calls**: messages are fetched one by one. Fine for tens of emails; a batch request would be the next optimization for hundreds.
- **bioRxiv only**: the crawler uses the bioRxiv API; medRxiv is not crawled.

---

All code in this project was written by [Claude Code](https://claude.com/claude-code) (Anthropic).
