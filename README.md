# LarkLab

<p align="center">
  <img src="img/image.png" alt="LarkLab">
</p>

A personal research assistant that collects, organizes, and recommends papers. It runs entirely on your own machine: papers live in a local SQLite file, embeddings and summaries come from a local [Ollama](https://ollama.ai) server, and the only outside services it talks to are Gmail (read + trash), Slack (post), and public paper metadata APIs.

## What it does

| Feature | Command | In one sentence |
|---------|---------|-----------------|
| Scholar digest | `digest` | Reads your Google Scholar alert emails, fetches full abstracts, optionally summarizes them with a local LLM, scores each paper against your reference library, and posts a threaded digest to Slack. |
| Recommendations | `recommend` | Crawls the arXiv, bioRxiv and PubMed papers that are new since the last run, scores them against your reference library, and posts the closest matches to Slack. |
| Reference library | `db-*` | A small curated set of papers you care about, stored with vector embeddings. Everything above is scored against it. |

Nothing is filtered out of the Scholar digest: every paper in your alerts is shown, and similarity to your reference papers is only context. Filtering (a similarity threshold) applies to `recommend`, where the volume is too high to read everything.

## How it works

```
digest     Gmail → parse → dedup → full abstracts → summaries → similarity → Slack / JSON
recommend  arXiv + bioRxiv + PubMed crawl → drop papers you already have → similarity → threshold → Slack
db-add     DOI or URL → metadata from several sources → preview → embedding → duplicate check → SQLite
```

- **Embeddings**: Ollama `qwen3-embedding:8b`, 1024 dimensions, cosine similarity on `title + abstract`.
- **Storage**: one SQLite file, `data/larklab.db`, with [sqlite-vec](https://github.com/asg017/sqlite-vec) for vector search.
- **Summaries**: Ollama `qwen3:8b`, only with `digest --summary`.
- **Privacy**: no paper text is sent to a hosted LLM.

## Quick start

```bash
# 1. dependencies (pixi installs Python and everything else)
pixi install

# 2. local models
ollama pull qwen3-embedding:8b
ollama pull qwen3:8b            # only needed for `digest --summary`

# 3. credentials: see docs/setup-guide.md for Gmail and Slack
cp .env.example .env

# 4. seed the reference library with a few papers you like
pixi run db-add 10.1038/s41586-021-03819-2

# 5. try it without posting anywhere
pixi run digest --batches 1 --no-slack
pixi run recommend arxiv --no-slack   # arXiv only: PubMed alone is hours of embedding
```

Only the reference library is needed to try `recommend arxiv --no-slack`; Gmail and Slack are needed only for `digest` and for posting.

## Commands

Run them as `pixi run <command>`; add `--help` for the options. Every option, the PubMed journal filter and how the library behaves are in [docs/commands.md](docs/commands.md).

| Command | What it does |
|---------|--------------|
| `digest` | Read Scholar alert emails and post a digest. Useful: `--summary`, `--cleanup` (trash delivered emails), `--no-slack` |
| `recommend [SOURCE...]` | Post the new papers closest to your library. Sources: `arxiv`, `biorxiv`, `pubmed` (none = all). Useful: `-t` minimum similarity, `-n` how many, `-c` categories or journals, `--no-slack` |
| `db-add <doi-or-url>` | Add a paper to the reference library |
| `db-list`, `db-search`, `db-edit`, `db-delete` | Browse and fix the library |
| `db-check`, `db-rebuild` | Find problems, re-embed everything |
| `db-export`, `db-import` | Back up and restore |

## Scheduling

Run it from cron (on macOS, launchd also works; see [docs/scheduling.md](docs/scheduling.md)):

```bash
# Digest at 8:00 AM
0 8 * * * cd /path/to/larklab && /path/to/pixi run digest --days-back 999 --max-results 200 --batches 5 --cleanup >> /tmp/larklab.log 2>&1
# arXiv and bioRxiv at 11:00 AM, after arXiv's morning announcement
0 11 * * * cd /path/to/larklab && /path/to/pixi run recommend arxiv biorxiv -n 999 >> /tmp/larklab.log 2>&1
# PubMed on its own: thousands of papers a day, so the run takes an hour or two
0 12 * * * cd /path/to/larklab && /path/to/pixi run recommend pubmed -t 0.6 -n 999 >> /tmp/larklab.log 2>&1
```

- `-n 999` posts every paper above the threshold instead of the top 20. PubMed is far larger, so it gets a higher threshold (`-t 0.6`).
- Keep the two `recommend` lines an hour apart: they write the same state files.
- cron runs whatever branch is checked out in the project directory. Keep it on a stable branch and develop in a separate `git worktree`.

## Documentation

- [Setup guide](docs/setup-guide.md): Gmail, `.env`, models, first run, troubleshooting
- [Slack setup](docs/slack-setup.md)
- [Command reference](docs/commands.md): every option, PubMed journals, library behaviour
- [Scheduling](docs/scheduling.md): cron notes and launchd
- [Example output](docs/example-output.md): terminal, Slack and `--output-json`
- [Crawl categories](docs/crawl-categories.md)
- [Architecture](docs/architecture.md): code layout, data flow, design decisions, known limitations

## Development

```bash
pixi install
pixi run pre-commit install   # ruff (lint + format) and the papers.md export run on every commit
pixi run test                 # offline: no network, no Ollama, no Gmail, no Slack
pixi run lint
```

The tests mirror the source tree and use fake sources and a temporary SQLite file. Scripts that touch live Gmail or Slack live in `scripts/manual/`, not in `tests/`. Conventions are in [CLAUDE.md](CLAUDE.md).

---

All code in this project was written by [Claude Code](https://claude.com/claude-code) (Anthropic).
