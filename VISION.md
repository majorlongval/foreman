# Project: FOREMAN — Self-Improving Autonomous Dev Pipeline

## Mission

Build a self-sustaining autonomous agent system that manages its own development
pipeline. It refines vague tasks into actionable specs, generates new tasks when
the pipeline runs dry, and eventually implements them — all with human oversight
at critical checkpoints.

The system bootstraps itself: it creates, refines, and works on the very tasks
that define how to build... itself.

## Principles

1. **Non-destructive by default** — Never modify existing issues. Create new ones,
   tag originals as `deprecated`. Every action is reversible.
2. **Human-in-the-loop where it matters** — Generated tasks (`draft`) require human
   approval before entering the pipeline. Refined tasks can be reviewed but flow
   automatically.
3. **Cost-aware** — Track API spend per agent per session. Route to cheapest model
   that can handle the task (Opus for strategy, Sonnet for coding, Haiku for
   mechanical work).
4. **Bootstrap-first** — The system builds itself. Every feature ships through the
   pipeline it creates.
5. **Auditable** — Every issue links to its origin. Every agent action is logged.
   The full history is reconstructable from GitHub Issues alone.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    FOREMAN                           │
│                                                     │
│  ┌───────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ REPL Loop │  │ Telegram │  │ React Dashboard  │ │
│  │ (Python)  │◄─┤ Bot      │  │ (monitoring)     │ │
│  │           │  │ (cmd/ctrl)│  │                  │ │
│  └─────┬─────┘  └──────────┘  └──────────────────┘ │
│        │                                            │
│        ▼                                            │
│  ┌──────────────────────────────────────────┐       │
│  │           GitHub Issues                   │       │
│  │  (task store + audit trail)               │       │
│  └──────────────────────────────────────────┘       │
│        │                                            │
│        ▼                                            │
│  ┌──────────────────────────────────────────┐       │
│  │           Claude API                      │       │
│  │  (intelligence layer)                     │       │
│  │  Foreman routing: opus / sonnet / haiku   │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

## Tech Stack

- **Runtime**: Python 3.11+ in Docker container
- **Task Store**: GitHub Issues via GitHub API (PyGithub)
- **AI**: Anthropic Claude API (anthropic Python SDK)
- **Hosting**: Railway or Fly.io (free/cheap tier)
- **Human Interface**: Telegram Bot (python-telegram-bot)
- **Dashboard**: React app (separate service, reads agent state)
- **CI/CD**: GitHub Actions

## Refined Ticket Structure

Every refined ticket MUST include these sections:

```markdown
## Summary
One-line description of what this task accomplishes.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] ...

## Steps to Reproduce (bugs only)
1. Step 1
2. Step 2
3. Expected vs actual behavior

## Component/Area
Which part of the system this touches (e.g., agent-loop, telegram-bot,
dashboard, github-integration, infrastructure).

## Subtasks
- [ ] Subtask 1
- [ ] Subtask 2

## Complexity Estimate
T-shirt size: XS / S / M / L / XL
Estimated API cost: low / medium / high
```

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
   IMPLEMENT (human or agent)
        │
        ├── creates PR → REVIEW AGENT posts comments
        └── on merge → issue closed
```

Filtering convention:
- Open issues = active work
- Closed + `refined-out` = originals that spawned better versions (audit trail)
- Closed (no special label) = completed work

## Agents

| Agent | File | Purpose | Runs |
|-------|------|---------|------|
| Seed / Refiner | `seed_agent.py` | Refines & brainstorms issues | Continuous loop |
| PR Reviewer | `review_agent.py` | Reviews PRs, posts comments | Continuous loop |
| Foreman (planned) | `foreman.py` | Telegram cmd/ctrl + orchestration | Continuous loop |

## Safety Rails

- **Infinite loop guard**: Never process issues labeled `auto-refined`,
  `refined-out`, or `draft`. Only touch `needs-refinement`.
- **Autonomous by design**: Agents run unattended in cloud containers.
  No permission prompts, no sandboxes. Safety comes from code-level
  guardrails, not human approval on each action.
- **Brainstorm throttle**: Max 5 draft issues per brainstorm cycle. Pause
  and notify human via Telegram after generating.
- **Cost ceiling**: Hard stop at $X/day (configurable). Agent parks itself
  and alerts human.
- **Duplicate detection**: Before creating a draft, check similarity against
  all open issues. Skip if >80% semantic match.
- **Rate limiting**: Minimum 30s between API calls. Backoff on 429s.
- **PR review safety**: Reviewer never auto-merges. Posts comments only.
  Humans merge.

## Roadmap

### Phase 1 — Seed (CURRENT)
> Goal: Minimal viable loop that can refine and generate its own tasks.

- [ ] VISION.md (this file)
- [ ] Seed agent script — poll / refine / brainstorm loop
- [ ] PR review agent — watches PRs, posts code review comments
- [ ] GitHub Issues integration (create, label, close-with-link)
- [ ] Brainstorm mode grounded in VISION.md
- [ ] Basic Telegram bot — status, pause, resume, queue
- [ ] Wire dashboard to real agent state
- [ ] Deploy to Railway
- [ ] Agent processes its own Phase 1 tasks

### Phase 2 — Implementation Agent
> Goal: The system writes code, not just tickets.

- [ ] Implementation agent — reads refined ticket, writes code, opens PR
  - Clone repo → create branch → implement based on acceptance criteria
  - Run tests/lint before pushing
  - Open PR with description linking back to issue
  - Review agent auto-reviews the PR
  - Human merges (for now)
- [ ] Model routing (foreman pattern)
  - Opus: planning step (read ticket → decide approach → file list)
  - Sonnet: coding step (write the actual code)
  - Haiku: mechanical steps (commit messages, PR descriptions)
- [ ] Feedback loop — track what gets changed in code review
- [ ] Start with easy targets: docs, configs, tests, README updates
- [ ] Graduate to real code changes as confidence builds

### Phase 3 — Brainstorm Conversations
> Goal: Multi-turn strategic planning via Telegram, not one-shot ticket generation.

- [ ] Telegram brainstorm mode — conversational, not fire-and-forget
  - Agent proposes direction based on VISION.md + current state
  - Human pushes back, adds context, redirects
  - Agent refines the plan across multiple exchanges
  - Final output: full implementation plan → decomposed into tickets
  - Tickets auto-created as "draft" for human approval
- [ ] Session persistence — brainstorm can span hours/days
- [ ] Context loading — agent reads repo state, recent PRs, recent
  issues, cost history before starting a brainstorm
- [ ] Plan templates — architecture decisions, feature specs, refactors
- [ ] "Think harder" mode — route brainstorm to Opus for deeper reasoning

### Phase 4 — Multi-Agent Orchestration
> Goal: Parallel specialized agents managed by a foreman.

- [ ] Foreman orchestrator — routes tasks to specialist agents
- [ ] Parallel execution with conflict detection (file-level locking)
- [ ] Agent specialization (refiner, implementer, reviewer, tester)
- [ ] Cross-agent communication protocol
- [ ] Scaling rules (spin up/down agents based on queue depth)
- [ ] Cost tracking dashboard (per agent, per session, per model)
- [ ] Prompt versioning — track which prompts produce best results

### Phase 5 — Production
> Goal: Battle-tested system ready for real project use.

- [ ] Migrate to Jira + GitLab integration for Robotiq use
- [ ] Multi-repo support
- [ ] Team onboarding (other devs interact via Telegram/dashboard)
- [ ] Security audit (API key management, permissions)
- [ ] Metrics and reporting (velocity, quality scores, cost efficiency)
- [ ] GCP cost monitoring with auto-shutdown

## Agent Evolution Path

The agents graduate in capability:

```
REFINE (now)          → reads ticket, writes better ticket
  ↓
IMPLEMENT (phase 2)   → reads ticket, writes code, opens PR
  ↓
BRAINSTORM (phase 3)  → multi-turn planning, generates roadmap
  ↓
ORCHESTRATE (phase 4) → manages other agents, routes work
```

Each level builds on the last. Refinement teaches the system what good
tickets look like. Implementation teaches it what good code looks like.
Brainstorming teaches it what good plans look like. Orchestration is
just routing to the right capability at the right time.

## Constraints & Non-Goals

- **NOT** building a general-purpose agent framework (no OpenClaw)
- **NOT** replacing human judgment on architecture decisions
- **NOT** auto-merging code without human review (until Phase 4+)
- **NOT** running untrusted third-party skills/plugins
- Target: **< $5/day** API spend during POC
- Target: **< 2 min** per ticket refinement
- Target: **> 80%** of refined tickets usable without human edits
- Target: **< $0.50** per implemented PR (average)

## Context

This project is a personal POC built by Jordan. If successful, the pattern
could be adapted for use at Robotiq (Jira + GitLab) for automating the
helpdesk → ticket → resolution pipeline for palletizer installations.

The long-term vision is an autonomous development team that a single human
can supervise via Telegram while doing other things (like parenting a toddler).
