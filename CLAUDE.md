# CLAUDE.md

Instructions for AI assistants working on this project.

## Behavioral Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

From: <https://github.com/forrestchang/andrej-karpathy-skills>

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## 6. Commit Conventions

Follow `.github/git_commit_template.md` for commit messages.

- Format: `<Type>: <Subject>` (e.g., `Feat: Add classifier-free guidance`)
- Types: Feat, Fix, Refactor, Design, Comment, Style, Test, Chore, Init, Rename, Remove
- Subject: Capitalize first letter, imperative mood, no trailing period, max 50 chars
- Body: Wrap at 72 chars, explain WHAT and WHY
- Before committing, ensure pre-commit hooks are installed: `pixi run pre-commit install`

## 7. PR Conventions

- User creates PRs on GitHub web, NOT via `gh` CLI
- Provide PR title and body as copy-pasteable code blocks
- PR title follows `<Type>: <Subject>` format
- Always write in English (all files, commit messages, PR descriptions)
- Follow `.github/pull_request_template.md` sections:
  - **Summary**: One-sentence overview
  - **Key Changes**: Bullet list of main changes
  - **Implementation Details**: Architecture/design decisions
  - **Trouble Shooting**: Issues encountered during implementation
  - **Known Issues & Notes**: Caveats, pre-existing issues
  - **Screenshots**: If applicable
  - **Related Issues**: Link related issues

## Project Rules

- All code and documentation in English
- Use `src/` layout — all Python source under `src/larklab/`
- Use pixi with `pyproject.toml` — do NOT create `requirements.txt`
- Use dataclasses for data transfer between modules
- Each module has one public interface — keep it that way
- `sources/gmail/scholar_alert_parser.py` is fragile (depends on Google's HTML format) — isolate all parsing logic there. Called via the `GmailClient.parse_emails` facade, not directly.
- **Layering**: dependencies point downward only — `cli → pipelines → sources / processing / library → models`; `outputs` depends on `models` alone; `utils` depends on nothing in the project. Keep it cycle-free.
- **Where code goes**: folder and file names must say what the code is. `sources/` reads outside systems, `processing/` improves fetched papers, `library/` is the reference library, `outputs/` sends results out, `utils/` holds small project-agnostic helpers, `cli/` only parses options and prints. Split a module by job, and name files after the job (`cli/library/add.py`, not `cli/library_stuff.py`).
- **One module per external source**: each file in `sources/papers/` talks to one service and exposes `fetch_by_*(…) -> Paper | None`. Source priority and merging live only in `sources/papers/metadata_lookup.py`. DOI prefixes live in `utils/identifiers.py`.
- **Recommendations are incremental and lossless**: `recommend` resumes each source from `data/crawl_progress.json`, which moves only when the crawl read everything (`CrawlResult.complete`). Recommendations Slack refused are queued in `data/outbox.json` and posted with the next run. Save pending before advancing progress. arXiv lists papers only after announcement, so never go back to a fixed "yesterday" window. Nothing in tests or dev runs may post to Slack: use fakes or `--no-slack`.
- Library code reports progress with `logging` (logger `larklab`), never `print`; only `cli/` and `outputs/terminal.py` print.
- Writes to the library go through `PaperRepository` and stay transactional — compute embeddings first, then swap.
- Tests are offline (fake sources, temp SQLite) and mirror the source tree folder by folder. Scripts that touch live Gmail/Slack go in `scripts/manual/`, never in `tests/`.
- "New articles" emails must always be included in summaries — never skip or filter them out
- Summarizer uses Ollama (qwen3:8b) locally — do not call external APIs for summarization
- Gmail `send` scope is intentionally excluded — only `readonly` and `modify` are used
- **Bot reusability**: `pipelines/` (`scholar_digest.py`, `paper_recommendations.py`) is designed for reuse by a future interactive bot — keep it pure (no printing, no click, no shared mutable config) and parameterizable via `DigestOptions` / function arguments
- **Configuration approach**: `.env` for sensitive info only (tokens, credentials); CLI arguments (click) for all other settings
- **Embedding/DB**: Use `sqlite-vec` + Ollama `qwen3-embedding:8b` (MRL truncated to 1024d, cosine distance). No external vector DB services. Single `papers` table for reference papers, `papers_vec` for embeddings.
  - Embedding input: `title + "\n" + abstract`
  - DB location: `data/larklab.db` (gitignored)
  - `db-add` accepts URL or DOI and requires a DOI to save. Lookup order: PubMed (DOI) → arXiv → CrossRef → bioRxiv; each later source only fills empty fields, and a web page is used only if no title was found. Shows preview before saving, detects near-duplicates
  - `db-*` commands: add, edit, delete, check, list, search, export, import, rebuild
  - `db-export --md` outputs title + URL + DOI; `db-import --md` refetches metadata via DOI/URL and rebuilds DB (asks before replacing; `--yes` skips). `papers.md` is lossy — use `db-export` JSON or the `.db` file for backups
  - `db-check` also reports papers with no embedding; fix with `db-rebuild`
  - DOI stored as column in `papers` table; extracted from PubMed XML, `citation_doi` meta tag, or URL
  - Digest: scores all papers against references (top 3), sorted by top-1 reference, no filtering — all shown

## Adding dependencies

```bash
pixi add <conda-package>
pixi add --pypi <pypi-package>
```

## Running

```bash
pixi run digest
pixi run test    # offline suite
pixi run lint
```

The daily cron jobs run whatever branch is checked out in the project directory — keep it on a stable branch and develop in a separate `git worktree`.


## Key warnings

- `credentials/` is gitignored — never commit OAuth secrets
- `.env` is gitignored — never commit environment variables
- Keep `docs/` and `README.md` updated when making significant changes
