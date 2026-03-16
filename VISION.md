# Project: FOREMAN — Self-Growing Autonomous Dev Organism

## Mission

FOREMAN is a self-growing software organism. Given a daily budget (energy), it
decides what to work on, writes the code, reviews it, fixes it, and ships it.

The human role is: set the budget, approve PRs (natural selection), and
occasionally redirect via Telegram. That's it.

Budget is energy. PR approval is natural selection. Growth is purpose.

## Principles

1. **Budget is the throttle** — The daily API spend ceiling is the primary human
   control surface. Everything else runs autonomously within that limit.
2. **Minimal human surface** — The only justified human touchpoints are: (a) setting
   direction via VISION.md or Telegram, (b) PR approval, (c) emergency override.
3. **Cost-aware** — Track API spend per agent per session. Route to cheapest model
   that can handle the task. Log all costs to shared memory.
4. **Bootstrap-first** — The system builds itself. Every feature ships through the
   pipeline it creates.
5. **Auditable** — Every issue links to its origin. Every agent action is logged.
   The full history is reconstructable from GitHub alone.
6. **Non-destructive by default** — Never modify existing issues. Create new ones,
   tag originals as `deprecated`. Every action is reversible.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    FOREMAN ORGANISM                  │
│                                                     │
│  ┌───────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ Brain Loop │  │ Telegram │  │   config.yml     │ │
│  │ (schedule) │◄─┤ Bot      │  │ (organism DNA)   │ │
│  │           │  │ (cmd/ctrl)│  │                  │ │
│  └─────┬─────┘  └──────────┘  └──────────────────┘ │
│        │                                            │
│        ▼                                            │
│  ┌──────────────────────────────────────────┐       │
│  │            Council                        │       │
│  │  Reads config, memory, issues, PRs        │       │
│  │  Decides what to do next                  │       │
│  │  Delegates to agents                      │       │
│  └──────────────────────────────────────────┘       │
│        │                                            │
│        ▼                                            │
│  ┌──────────────────────────────────────────┐       │
│  │            Agents                         │       │
│  │  Gandalf (Scout) — explore, brainstorm    │       │
│  │  Gimli (Builder) — implement, fix         │       │
│  │  Galadriel (Critic) — review, quality     │       │
│  │  Samwise (Gardener) — maintain, clean     │       │
│  └──────────────────────────────────────────┘       │
│        │                                            │
│        ▼                                            │
│  ┌──────────────────────────────────────────┐       │
│  │            Tools                          │       │
│  │  GitHub API, LLM providers, Telegram      │       │
│  │  Memory read/write, Cost tracking         │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

## Tech Stack

- **Runtime**: Python 3.11+, GitHub Actions
- **Task Store**: GitHub Issues via GitHub API (PyGithub)
- **AI**: Provider-agnostic via LiteLLM (Gemini, Anthropic, OpenAI-compatible)
- **Configuration**: `config.yml` (organism DNA — models, budget, agent roster)
- **Human Interface**: Telegram Bot (python-telegram-bot)
- **CI/CD**: GitHub Actions (brain loop, agent cycles)

## Agents

| Agent | Role | Identity | Purpose |
|-------|------|----------|---------|
| Gandalf | Scout | `agents/gandalf.md` | Explore codebase, brainstorm ideas, find opportunities |
| Gimli | Builder | `agents/gimli.md` | Implement features, fix code, open PRs |
| Galadriel | Critic | `agents/galadriel.md` | Review PRs, enforce quality, approve/reject |
| Samwise | Gardener | `agents/samwise.md` | Maintain tests, docs, memory, backlog hygiene |

Legacy agents (being absorbed into organism):

| Agent | File | Purpose |
|-------|------|---------|
| Seed / Refiner | `seed_agent.py` | Refines & brainstorms issues |
| Implementer | `implement_agent.py` | Reads tickets, writes code, opens PRs |
| PR Reviewer | `review_agent.py` | Reviews PRs, posts structured review |
| Fix Agent | `fix_agent.py` | Reads review, pushes search/replace patches |
| Brain | `foreman_brain.py` | Telegram bot with Claude + GitHub tools |

## Issue Lifecycle

```
  BRAINSTORM MODE              HUMAN CREATES
  (agent generates             (manual entry)
   from VISION.md)                  │
        │                           │
        ▼                           │
    label: "draft"                  │
        │                           │
   human reviews                    │
   approves / modifies              │
   relabels ────────────────────────┤
        │                           │
        ▼                           ▼
    label: "needs-refinement"
        │
   REFINE MODE
   (agent rewrites)
        │
        ├── creates new issue: label "auto-refined"
        └── closes original: label "refined-out" + comment linking to new
        │
        ▼
    label: "ready"
    (implementation queue)
        │
   IMPLEMENT (agent)
        │
        ├── creates PR → REVIEW AGENT posts comments
        └── on merge → issue closed
```

## Safety Rails

- **Cost ceiling**: Hard stop at configurable daily limit (`config.yml`). Agent
  parks itself and alerts via Telegram.
- **PR approval gate**: Every code change requires Jord's approval. This is
  natural selection — bad mutations get rejected.
- **Syntax check before commit**: All Python files validated with `ast.parse()`
  before being pushed to a branch.
- **Fix cycle cap**: Fix agent stops after N review rounds (default 5) and
  escalates with `needs-human` label.
- **Duplicate detection**: Before creating a draft, check semantic similarity
  against all open issues. Skip if match > threshold.
- **Brainstorm throttle**: Max N draft issues per cycle. Hard stop when
  open issue count exceeds ceiling.
- **Telegram override**: Human can pause, redirect, or veto any action via Brain.

## Roadmap

### Phase 1 — Seed (DONE)
Seed agent, refine loop, brainstorm grounded in VISION.md, GitHub Issues integration,
Telegram notifications, cost ceiling, duplicate detection.

### Phase 2 — Implementation (DONE)
Implement agent, review agent, fix agent, Foreman Brain (Telegram bot with
Claude + GitHub tools for conversational control).

### Phase 3 — Organism Redesign (CURRENT)
> Goal: Transform from a pipeline of scripts into a self-governing organism.

- **Constitution**: `PHILOSOPHY.md` — shared values and rules every agent reads
- **Exposed DNA**: `config.yml` — budget, models, agent roster (agents can propose changes)
- **Agent identities**: Named characters with distinct roles and personalities
- **Memory system**: Private per-agent memory + shared commons
- **Council**: Deliberation step where agents decide what to do next
- **Brain loop**: Scheduled cycle that reads state, runs council, delegates work
- **Self-improvement**: Agents can propose changes to their own code, config, and roster

### Phase 4 — Scale & Evolve
> Goal: The organism runs 24/7, grows capabilities, and generates value.

- Cost dashboard — per agent, per day, trend over time
- Velocity metrics — issues closed per week, PR cycle time
- Budget auto-scaling — spend more on active days, less on idle
- New agent types as the organism discovers needs
- Multi-repo support
- External tool integration (web search, API exploration)

## Cost Targets

- **< $5/day** API spend during growth phase
- **< $0.50** per implemented PR (average)
- **< 2 min** per ticket refinement

## Context

Personal project built by Jordan (Jord). The goal is a system that grows like
a living organism: given a daily budget, it decides what to build, builds it,
reviews it, and ships it. The human sets direction (this file + Telegram),
approves PRs (natural selection), and watches it grow.
