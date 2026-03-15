# 🤖 FOREMAN — Self-Improving Autonomous Dev Pipeline

A bootstrapping agent system that refines, generates, and eventually implements its own
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
├── VISION.md             # The north star
├── brainstorm_agent.py   # Generates draft tasks
├── refine_agent.py       # Turns drafts into specs
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
#   FOREMAN_REPO  — e.g. "jordanuser/foreman"
```

### 4. Create your first issues

Create 2-3 rough issues on the repo with the label `needs-refinement`:

- "set up the basic telegram bot for foreman"
- "add cost tracking to the dashboard"
- "write tests for the refine loop"

These are intentionally vague — the agent will refine them.

### 5. Run it locally

```bash
# Install deps
pip install -r requirements.txt

# Brainstorm new drafts (based on VISION.md)
python brainstorm_agent.py --dry-run
python brainstorm_agent.py

# Refine pending issues (labeled 'needs-refinement')
python refine_agent.py --dry-run
python refine_agent.py
```

### 6. Automated Workflows (GitHub Actions)

FOREMAN is designed to run automatically via GitHub Actions:

- **Brainstorm Workflow**: Runs on a schedule or manual trigger to ensure the pipeline is never empty.
- **Refine Workflow**: Triggered instantly whenever you add the `needs-refinement` label to an issue.

## Issue Lifecycle

```
  BRAINSTORM creates "draft" issues
         │
    you review + approve (relabel → "needs-refinement")
         │
    agent REFINES → creates "auto-refined" issue
                  → tags original "deprecated"
         │
    ready for implementation
```

## Commands

| Command | What it does |
|---------|-------------|
| `python brainstorm_agent.py` | Generate draft issues from VISION.md |
| `python refine_agent.py` | Process all issues labeled `needs-refinement` |
| `--dry-run` | Log everything, touch nothing |
| `--once` | Single pass, then exit (default) |

## Environment Variables

| Var | Default | Description |
|-----|---------|-------------|
| `GITHUB_TOKEN` | required | GitHub PAT with repo scope |
| `ANTHROPIC_API_KEY` | required | Anthropic API key |
| `FOREMAN_REPO` | required | `owner/repo` format |
| `BRAINSTORM_THRESHOLD` | `2` | If queue < this, brainstorm |
| `BRAINSTORM_MAX_DRAFTS` | `5` | Max drafts per brainstorm |
| `COST_CEILING_USD` | `5.0` | Daily spend limit |
| `MODEL_REFINE` | `claude-sonnet-4-20250514` | Model for refinement |
| `MODEL_BRAINSTORM` | `claude-sonnet-4-20250514` | Model for brainstorm |

## What happens next

The system will refine its own tasks, then brainstorm new ones. You approve
the drafts, and the cycle continues. Over time, the system builds out:

1. Telegram bot (so you can manage it from your phone)
2. Real-time dashboard (wired to live agent state)
3. Code implementation mode (auto-PRs)
4. Multi-agent orchestration

See [VISION.md](./VISION.md) for the full roadmap.