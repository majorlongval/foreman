# 🤖 FOREMAN — Self-Improving Autonomous Dev Pipeline

A bootstrapping agent that refines, generates, and eventually implements its own
development tasks. Point it at a GitHub repo and it starts building itself.

## Quickstart

### 1. Create the GitHub repo

```bash
gh repo create foreman --public --clone
cd foreman
```

### 2. Copy these files in

```
foreman/
├── VISION.md          # The north star
├── seed_agent.py      # The agent loop
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

### 3. Set up environment

```bash
cp .env.example .env
# Edit .env with your tokens:
#   GITHUB_TOKEN  — needs 'repo' scope (github.com/settings/tokens)
#   ANTHROPIC_API_KEY — from console.anthropic.com
#   PERPLEXITY_API_KEY — from perplexity.ai (for research agent)
#   FOREMAN_REPO  — e.g. "jordanuser/foreman"
```

### 4. Create your first issues

Create 2-3 rough issues on the repo with the label `needs-refinement`:

- "set up the basic telegram bot for foreman"
- "add cost tracking to the dashboard"
- "write tests for the refine loop"

These are intentionally vague — the agent will refine them.

### 5. Run it

```bash
# Install deps
pip install -r requirements.txt

# Dry run first (logs what it would do, doesn't touch GitHub)
python seed_agent.py --once --dry-run

# Single pass for real
python seed_agent.py --once

# Force brainstorm mode
python seed_agent.py --brainstorm-only --dry-run

# Full loop
python seed_agent.py
```

### 6. Deploy to cloud (Railway)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Deploy
railway login
railway init
railway up

# Set env vars
railway variables set GITHUB_TOKEN=ghp_xxx
railway variables set ANTHROPIC_API_KEY=sk-ant-xxx
railway variables set PERPLEXITY_API_KEY=pplx-xxx
railway variables set FOREMAN_REPO=youruser/foreman
```

## Issue Lifecycle

```
  BRAINSTORM creates "draft" issues
         │
    you review + approve (relabel → "needs-refinement")
         │
    agent REFINES → creates "auto-refined" issue
                  → tags original "deprecated"
         │
    READY (relabel → "ready")
         │
    EXECUTION:
    - If label "research": Research Agent (Perplexity) → Markdown PR
    - Otherwise: Implementation Agent → Code PR
```

## Commands

| Command | What it does |
|---------|-------------|
| `--once` | Single pass, then exit |
| `--brainstorm-only` | Skip refinement, force brainstorm |
| `--dry-run` | Log everything, touch nothing |

## Environment Variables

| Var | Default | Description |
|-----|---------|-------------|
| `GITHUB_TOKEN` | required | GitHub PAT with repo scope |
| `ANTHROPIC_API_KEY` | required | Anthropic API key |
| `PERPLEXITY_API_KEY` | optional | Perplexity API key for research agent |
| `FOREMAN_REPO` | required | `owner/repo` format |
| `POLL_INTERVAL` | `60` | Seconds between passes |
| `BRAINSTORM_THRESHOLD` | `2` | If queue < this, brainstorm |
| `BRAINSTORM_MAX_DRAFTS` | `5` | Max drafts per brainstorm |
| `COST_CEILING_USD` | `5.0` | Daily spend limit |
| `MODEL_REFINE` | `claude-sonnet-4-20250514` | Model for refinement |
| `MODEL_BRAINSTORM` | `claude-sonnet-4-20250514` | Model for brainstorm |

## What happens next

The agent will refine its own tasks, then brainstorm new ones. You approve
the drafts, and the cycle continues. Over time, the agent builds out:

1. Telegram bot (so you can manage it from your phone)
2. Real-time dashboard (wired to live agent state)
3. Code implementation mode (auto-PRs)
4. Research mode (automated markdown summaries via Perplexity)
5. Multi-agent orchestration

See [VISION.md](./VISION.md) for the full roadmap.