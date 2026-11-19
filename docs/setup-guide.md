# Setup Guide

## Prerequisites

- macOS / Linux
- Python 3.12+
- [pixi](https://pixi.sh) — install with: `curl -fsSL https://pixi.sh/install.sh | bash`
- [Ollama](https://ollama.ai) — local embeddings and summaries
- A Google account with Gmail

## Step 1: Clone and Install

```bash
git clone https://github.com/JaeKyoung/larklab.git
cd larklab
pixi install
```

## Step 2: Google Cloud Setup

### Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
3. Name it (e.g., "larklab") and create

### Enable Gmail API

1. In the Cloud Console, go to **APIs & Services** → **Library**
2. Search for "Gmail API"
3. Click **Enable**

### Create OAuth Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth 2.0 Client ID**
3. If prompted, configure the OAuth consent screen:
   - User type: **External** (or Internal if using Google Workspace)
   - App name: "larklab"
   - Add your email as a test user
4. Application type: **Desktop application**
5. Download the JSON file
6. Save it as `credentials/credentials.json` in the project root

## Step 3: Install Ollama Models

```bash
ollama pull qwen3-embedding:8b   # embeddings: needed by everything
ollama pull qwen3:8b             # summaries: only for `digest --summary`
```

Both run locally; no paper text is sent to a hosted LLM.

## Step 4: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` to add your Slack bot token if using Slack output:

```
SLACK_BOT_TOKEN=xoxb-your-token-here
```

`.env` holds secrets and file paths only; every other setting is a command-line option (see `pixi run digest --help`).

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_CREDENTIALS_PATH` | `credentials/credentials.json` | OAuth client credentials |
| `GMAIL_TOKEN_PATH` | `credentials/token.json` | Where the OAuth token is stored |
| `SLACK_BOT_TOKEN` | | Slack bot user OAuth token ([setup](slack-setup.md)) |

The database is always `data/larklab.db` (gitignored). `credentials/` and `.env` are gitignored; never commit them.

## Step 5: Set Up Slack (Optional)

See [slack-setup.md](slack-setup.md) for Slack Bot configuration.

## Step 6: First Run

```bash
pixi run digest
```

A browser window opens for OAuth consent. LarkLab requests only the `gmail.readonly` and `gmail.modify` scopes (read, and move to trash); the `send` scope is deliberately not requested. The token is saved to `credentials/token.json` with owner-only permissions and reused on later runs.

## Troubleshooting

### "Access blocked: This app's request is invalid"
- Make sure you added your Google account as a test user in the OAuth consent screen

### "File not found: credentials.json"
- Verify the file is saved at `credentials/credentials.json`
- Check that `GMAIL_CREDENTIALS_PATH` in `.env` matches the actual path

### No emails found
- Check your Gmail — do you actually receive Google Scholar alerts?
- Try increasing `--days-back` CLI option (e.g., `pixi run digest --days-back 30`)
- Verify the sender address matches `--query` CLI option

### While running

| Symptom | Likely cause and fix |
|---------|----------------------|
| Only bioRxiv papers show up in Slack | arXiv lists a paper only after it is announced, so "yesterday" is always empty. `recommend` resumes from `data/crawl_progress.json`; check the log for `Found N papers (arxiv: …)`. 429/503 from arXiv are retried per category and logged as `arXiv rate limited` / `arXiv crawl stopped`. |
| `db-check` says `missing: embedding` | The paper was stored without a vector, so similarity search cannot see it. Run `pixi run db-rebuild`. |
| `db-add` ends with "Could not determine a DOI" | The page does not expose a DOI. Find it on the publisher page and pass the DOI instead of the URL. |
| `db-add` shows `Journal: (none)` | The sources did not return a journal. Pass `--journal`. |
| Connection errors from `db-add`, `db-rebuild`, `digest` | Ollama is not running, or the model is not pulled: `ollama serve`, `ollama pull qwen3-embedding:8b`. |
| Slack posts nothing | `SLACK_BOT_TOKEN` is empty, or the bot is not invited to the channel. See [slack-setup.md](slack-setup.md). `digest` then keeps your emails; `recommend` keeps the recommendations in `data/outbox.json` and sends them with the next run. |
| The digest lists papers with short abstracts | Some sites block automated requests. The snippet from the email is kept (see Known limitations in [architecture.md](architecture.md)). |
