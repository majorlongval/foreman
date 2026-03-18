# FOREMAN — Self-Growing Dev Organism

A society of autonomous agents that lives in a GitHub repo. Give it a daily budget and it decides what to build, writes the code, reviews it, and ships it — including proposing changes to its own operating procedures.

## How It Works

Every cycle, the brain loop runs:

1. **Survey** — checks budget, open issues, open PRs, agent memories, shared memory
2. **Orchestrate** — Elrond reads the board and assigns one concrete task to each agent
3. **Execute** — each agent runs its task using the available toolset
4. **Reflect** — writes a journal entry, clears the inbox, delivers outbox via Telegram

Budget is energy. PRs are the unit of output. Growth is the purpose.

## The Society

| Agent | Role | Deliverable each cycle |
|-------|------|------------------------|
| **Elrond** | Orchestrator | Assigns tasks — does not build himself |
| **Gandalf** | Scout | A GitHub issue or a research doc in `memory/shared/` |
| **Gimli** | Builder | A new PR with working code |
| **Galadriel** | Critic | A PR review — comments, approve, and merge when ready |
| **Samwise** | Gardener | Maintenance — close stale issues, address review feedback |

Agents have distinct identities (defined in `agents/*.md`), private memory, and can **propose changes to their own identity files, PHILOSOPHY.md, and even `brain/tools.py`** via PR. This is how the society evolves.

## Toolset

Agents have access to 17 tools:

| Tool | Description |
|------|-------------|
| `list_files` | Browse the repo file tree |
| `read_file` | Read any file from the repo |
| `create_pr` | Create a branch, commit files (new or updated), open a PR |
| `push_to_pr` | Push additional commits to an existing PR's branch (for addressing review feedback) |
| `merge_pr` | Merge an approved PR (critic only) |
| `close_pr` | Close a PR without merging |
| `create_issue` | Open a new GitHub issue |
| `close_issue` | Close an issue |
| `list_issues` | List open issues |
| `list_prs` | List open PRs |
| `read_pr` | Read a PR's diff, body, and comments |
| `post_comment` | Post a comment on a PR |
| `approve_pr` | Approve a PR (critic only) |
| `read_memory` | Read own or shared memory |
| `write_memory` | Write to own or shared memory |
| `check_budget` | Check remaining daily budget |
| `send_telegram` | Message Jord directly |

## Key Files

```
PHILOSOPHY.md              # Constitution — agents can propose changes via PR
config.yml                 # Budget, models, agent roster
brain.py                   # CLI entry point — runs one brain cycle
brain/
  council.py               # Elrond orchestration (single LLM call per cycle)
  executor.py              # Tool-use loop — runs each agent's assigned task
  tools.py                 # Full toolset (16 tools)
  survey.py                # Gather world state
  loop.py                  # One complete cycle
  config.py                # Typed config loader
  memory.py                # Scoped memory with privacy enforcement
  cost_tracking.py         # JSONL cost persistence
agents/                    # Agent identity files (agents can modify these)
memory/
  shared/                  # Shared memory (journal, costs, incidents, plans)
  gandalf/ gimli/ ...      # Private per-agent memory
```

## Configuration

```yaml
budget:
  daily_limit_usd: 5.00

models:
  default: "gemini/gemini-3-flash-preview"
  elrond: "gemini/gemini-3-flash-preview"

agents:
  elrond:
    role: orchestrator
    identity: agents/elrond.md
  gandalf:
    role: scout
    identity: agents/gandalf.md
  # ... gimli, galadriel, samwise
```

## Running

### GitHub Actions (default)

The brain loop runs automatically via `.github/workflows/brain_loop.yml` every 15 minutes. A daily watchdog checks health and alerts via Telegram if something breaks.

Required secrets: `GH_PAT`, `GEMINI_API_KEY`, `FOREMAN_REPO`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### Local

```bash
pip install -r requirements.txt
export GITHUB_TOKEN=ghp_...
export FOREMAN_REPO=owner/repo
export GEMINI_API_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
python brain.py
```

## Memory & Privacy

Each agent has private memory only they can read/write. Shared memory (`memory/shared/`) is accessible to all. Privacy is enforced in code — agents only receive their own memory and shared memory. No agent can access another agent's private files.

All state persists as git-committed files. No in-memory state between runs.

## Safety

- **Budget ceiling** — hard stop at daily limit, alerts via Telegram
- **PR approval gate** — every code change requires Galadriel's review; merges only after approval
- **Human override** — agents flag risky decisions for Jord via `flag_for_jord`
- **Watchdog** — daily health check, alerts if the brain loop stops running

## Tech Stack

- Python 3.11+, GitHub Actions
- PyGithub (GitHub API)
- LiteLLM — provider-agnostic LLM client (Gemini, Anthropic, OpenAI-compatible)
- Telegram Bot for human communication
- pytest, full TDD (145 tests)

## See Also

- [`PHILOSOPHY.md`](./PHILOSOPHY.md) — the constitution
- [`config.yml`](./config.yml) — organism configuration
