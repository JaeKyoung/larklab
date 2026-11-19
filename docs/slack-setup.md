# Slack Bot Setup

## 1. Create a Slack App

1. Go to [Slack API Apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. App Name: `lark`
4. Select your workspace → **Create App**

## 2. Add Bot Permissions

1. In the left sidebar, go to **OAuth & Permissions**
2. Scroll to **Bot Token Scopes** and add:
   - `chat:write` — Send messages to channels
   - `chat:write.customize` — Customize bot name and icon per message
   - `commands` — Register slash commands (for future use)

## 3. Install and Configure

1. In the left sidebar, go to **Install App**
2. Click **Install to Workspace** and allow the permissions
3. Copy the **Bot User OAuth Token** (`xoxb-...`) that appears
4. Add the token to `.env`:

```bash
echo 'SLACK_BOT_TOKEN=xoxb-your-token-here' >> .env
```

The channel is configured via CLI argument: `pixi run digest --channel your-channel`

## 4. Customize Bot Profile (optional)

1. Go to **App Home** in the left sidebar
2. Under **Your App's Presence in Slack**, click **Edit**
3. Set display name and profile photo for the bot

## 5. Invite Bot to Channel

Create `#journal-club` channel (or your preferred channel), then invite the bot:

```
/invite @lark
```

To post to a different channel, use `--channel`: `pixi run digest --channel other-channel`

## 6. Discuss papers with an AI assistant (optional)

LarkLab only posts. To ask questions about a paper it posted, add an AI assistant to the channel and mention it in that paper's thread:

- **Claude Tag (Claude in Slack)**: run `/invite @Claude` in the channel (Slack rejects it inside a thread), then write `@Claude explain this paper` in a thread. It reads the thread and answers in place; later replies in that thread need no new mention. See [Use Claude in Slack](https://support.claude.com/en/articles/12461605-use-claude-in-slack).
- **ChatGPT**: `@ChatGPT` needs a ChatGPT Business, Enterprise or Edu workspace and an admin who has set it up; add it to the channel the same way. See [ChatGPT app in Slack](https://help.openai.com/en/articles/12462158-chatgpt-app-in-slack).
- **ChatGPT dots**: OpenAI's always-on personal agent, reachable from ChatGPT or Slack. It has its own cloud computer and keeps working between chats; only its owner can direct it, so teammates cannot use yours. Plan and region limits apply, and connecting it to Slack may need a Slack admin's approval. See [Getting started with your dot](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot).

These are separate products with their own plans and admin settings; LarkLab does not call them. The paper's details are in the card, which Slack stores as an attachment; if an assistant answers without them, paste the abstract into the thread. Replies are visible to everyone in the channel.

This is the one place where paper text leaves your machine for a hosted LLM: whatever is in the thread goes to that service. Skip it if that matters.

## Security

- **Never commit** the bot token to git (`.env` is gitignored)
- If the token is ever exposed, go to **OAuth & Permissions** in the Slack App settings and click **Regenerate** to get a new token
