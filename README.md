# FOREMAN — Self-Growing Dev Organism

A society of autonomous agents that lives in a GitHub repo. Give it a daily budget, and it decides what to build, writes the code, reviews it, and ships it. You approve PRs and watch it grow.

## How It Works

Every 2 hours, the **brain loop** runs one cycle:

1. **Survey** — checks budget, open issues, PRs, recent incidents, memory
2. **Deliberate** — each agent gives their perspective on what to prioritize
3. **Decide** — the rotating chair agent synthesizes and commits to an action
4. **Act** — executes the action plan using the seed toolset
5. **Reflect** — writes a journal entry to shared memory

Budget is energy. PR approval is natural selection. Growth is purpose.

## The Council

Four agents deliberate each cycle. The chair rotates so no single agent dominates.

| Agent | Role | Purpose |
|-------|------|---------|
| **Gandalf** | Scout | Explore the codebase, brainstorm ideas, find opportunities |
| **Gimli** | Builder | Implement features, fix code, open PRs |
| **Galadriel** | Critic | Review quality, catch problems, enforce standards |
| **Samwise** | Gardener | Maintain tests, docs, memory, backlog hygiene |

Agents have distinct personalities (defined in `agents/*.md`), private memory, and can propose changes to their own identities and the system config.

## Key Files

```
PHILOSOPHY.md              # Constitution every agent reads on startup
config.yml                 # Organism DNA: budget, models, agent roster
brain.py                   # CLI entry point — runs one brain cycle
brain/
  config.py                # Typed config loader
  memory.py                # Scoped memory with privacy enforcement
  cost_tracking.py         # JSONL cost persistence
  survey.py                # Gather world state for deliberation
  council.py               # Agent deliberation + chair rotation
  tools.py                 # Seed toolset (9 tools)
  loop.py                  # The Wiggum loop — orchestrates one cycle
agents/                    # Agent identity files
memory/
  shared/                  # Shared memory (decisions, journal, costs, incidents)
  gandalf/ gimli/ ...      # Private per-agent memory
```

## Configuration

All configuration lives in `config.yml` — agents can see it and propose changes via PR:

```yaml
budget:
  daily_limit_usd: 5.00

models:
  default: "gemini/gemini-2.5-flash"
  reasoning: "gemini/gemini-2.5-pro"
  council: "anthropic/claude-sonnet-4-6"

agents:
  gandalf:
    role: scout
    identity: agents/gandalf.md
    memory: memory/gandalf/
  # ... gimli, galadriel, samwise
```

## Running

### GitHub Actions (default)

The brain loop runs automatically via `.github/workflows/brain_loop.yml` every 2 hours. A daily watchdog checks health and alerts via Telegram if something breaks.

Required secrets: `GH_PAT`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `FOREMAN_REPO`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### Local

```bash
pip install -r requirements.txt

# Set environment variables
export GITHUB_TOKEN=ghp_...
export FOREMAN_REPO=owner/repo
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...

# Run one cycle
python brain.py
```

## Memory & Privacy

Each agent has private memory that only they can read/write. Shared memory (`memory/shared/`) is accessible to all. Privacy is enforced in code — the brain loop only injects an agent's own memory and shared memory into their context. No agent can access another agent's private files.

All state persists as files committed to git. No in-memory state between runs.

## Safety

- **Budget ceiling** — hard stop at daily limit, alerts via Telegram
- **PR approval gate** — every code change requires human approval
- **Watchdog** — daily health check, alerts if the brain loop stops running
- **Self-healing** — agents can fix each other's code and propose patches
- **Dispute resolution** — disagreements get flagged for Jord (the human)

## Tech Stack

- Python 3.11+, GitHub Actions
- PyGithub (GitHub API)
- LLM: provider-agnostic via LiteLLM (Gemini, Anthropic, OpenAI-compatible)
- Telegram Bot for human communication
- pytest for testing (68 tests, full TDD)

## See Also

- [`PHILOSOPHY.md`](./PHILOSOPHY.md) — the constitution
- [`VISION.md`](./VISION.md) — full roadmap and architecture
- [`config.yml`](./config.yml) — organism configuration
