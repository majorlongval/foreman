# Foreman Brain — Design

## What it is

A Telegram bot that lets you have conversations with Foreman about your project. It can answer questions about project status, brainstorm features with you, and trigger actions (start implementation, merge PRs, create issues).

It does NOT replace the existing agents. It orchestrates them. Seed, implement, and review agents stay on GitHub Actions. The Brain is a new layer on top.

## Architecture

```
You (Telegram)
    ↕
Foreman Brain (Python, always-on on Railway/Fly.io)
    ├── Telegram listener (python-telegram-bot, long-polling)
    ├── LLM conversation layer (Claude Sonnet, tool use)
    ├── GitHub tools (PyGithub)
    └── Project context (VISION.md, issues, PRs — fetched on demand)
    ↕
GitHub (issues, PRs, workflows)
    ↕
Existing agents (seed, implement, review — GitHub Actions, unchanged)
```

## Core capabilities (v1)

### 1. Brainstorm
Multi-turn conversation about ideas. When a concrete idea emerges, Brain asks "Should I create an issue?" and files it with `needs-refinement` label, feeding it into the existing pipeline.

### 2. Status
"What's going on?" — Brain fetches issues by label, open PRs, recent activity from GitHub API and summarizes.

### 3. Actions
- "Work on #27" → labels issue `ready`, triggers implement agent
- "Merge PR #42" → merges the PR
- "Create an issue about X" → creates issue with appropriate label

## LLM tools

```
Status:
  get_project_status(repo)              → issues by label, open PRs, recent activity
  get_issue(repo, number)               → issue details
  get_pr(repo, number)                  → PR details + diff + review comments

Actions:
  label_issue(repo, number, label)      → add label (e.g. "ready" triggers implement)
  merge_pr(repo, number)                → merge PR
  create_issue(repo, title, body, labels) → create issue into pipeline

Context:
  read_file(repo, path)                 → read any file from repo
  get_repo_tree(repo)                   → file listing
```

## Conversation management

- Message history kept in memory (Python list)
- `/new` command resets conversation history
- Project context (issues, PRs, files) fetched fresh from GitHub on every turn — not stored in conversation history
- Process restart = automatic reset (fine for v1)
- No persistent memory in v1

## Multi-project

- Bot stores `current_repo` per Telegram chat_id
- Default: `majorlongval/foreman`
- "Switch to other-repo" changes context
- All tools take repo as parameter — nothing hardcoded

## LLM choice

Claude Sonnet for the Brain conversation. Conversation tokens are small (1-2K in, few hundred out), so cost is negligible even with Claude. Sonnet is strong at tool use which matters here.

Existing agents keep their own routing profiles (currently `cheap` / Gemini).

## Deployment

- Extend existing `Dockerfile` or add a separate one for the Brain
- Deploy to Railway free tier (500 hrs/month) or Fly.io
- Environment variables: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `FOREMAN_REPO` (default repo)
- Long-polling mode (no webhook setup needed for v1)

## What this does NOT include (v1)

- Persistent conversation memory (later)
- Auto-merge with confidence scoring (later)
- Fix loop / review feedback processing (later, but Brain makes it easier to steer)
- Webhook-based notifications from GitHub → Telegram (later — for now, user asks for status)
- Web UI (Telegram is the interface)

## Connection to existing pipeline

The Brain creates issues and labels them. The existing pipeline picks them up:

```
Brain creates issue (needs-refinement)
    → Seed agent refines it (auto-refined)
    → Human or Brain labels it "ready"
    → Implement agent writes code, opens PR
    → Review agent reviews PR
    → Human or Brain merges PR
```

The Brain replaces the "go to GitHub and click labels" step with "tell Foreman in Telegram."
