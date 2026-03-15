# Project: FOREMAN — Self-Improving Autonomous Dev Pipeline

## Mission

FOREMAN is a self-growing software system. Like a plant, it only needs a daily
budget to run. It decides what to work on, writes the code, reviews it, fixes it,
and ships it — on its own.

The human role is: set the budget, read the Telegram updates, occasionally redirect
via chat. That's it.

The system bootstraps itself: it creates, refines, and works on the very tasks
that define how to build... itself.

## Principles

1. **Budget is the throttle** — The daily API spend ceiling is the primary human
   control surface. Everything else runs autonomously within that limit.
2. **Minimal human surface** — The only justified human touchpoints are: (a) setting
   direction via VISION.md or Telegram, (b) emergency override. Routine approvals
   are a failure mode, not a feature.
3. **Cost-aware** — Track API spend per agent per session. Route to cheapest model
   that can handle the task.
4. **Bootstrap-first** — The system builds itself. Every feature ships through the
   pipeline it creates.
5. **Auditable** — Every issue links to its origin. Every agent action is logged.
   The full history is reconstructable from GitHub Issues alone.
6. **Non-destructive by default** — Never modify existing issues. Create new ones,
   tag originals as `deprecated`. Every action is reversible.

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

- **Cost ceiling**: Hard stop at configurable daily limit. Agent parks itself
  and alerts via Telegram. This is the primary safety control.
- **Infinite loop guard**: Agents only touch issues in their designated label state.
  No agent processes its own output label.
- **Syntax check before commit**: All Python files validated with `ast.parse()`
  before being pushed to a branch.
- **Fix cycle cap**: Fix agent stops after N review rounds (default 5) and
  escalates with `needs-human` label.
- **Auto-merge threshold**: Only merge when review confidence > threshold AND
  zero open CRITICAL issues. When in doubt, escalate.
- **Duplicate detection**: Before creating a draft, check semantic similarity
  against all open issues. Skip if match > threshold.
- **Brainstorm throttle**: Max N draft issues per cycle. Hard stop when
  open issue count exceeds ceiling.
- **Telegram override**: Human can pause, redirect, or veto any action via Brain.

## Roadmap

### Phase 1 — Seed ✅ DONE
Seed agent, refine loop, brainstorm grounded in VISION.md, GitHub Issues integration,
Telegram notifications, cost ceiling, duplicate detection.

### Phase 2 — Implementation ✅ DONE
Implement agent (reads refined ticket → writes code → opens PR), review agent
(posts structured review), fix agent (reads review → pushes search/replace patches),
Foreman Brain (Telegram bot with Claude + GitHub tools for conversational control).

### Phase 3 — Close the Loop (CURRENT)
> Goal: Remove the two remaining manual steps so the system runs fully on budget alone.

**Gap 1: Auto-promote refined issues to `ready`**
- After refinement, issues sit at `auto-refined` waiting for a human to label them `ready`
- Seed agent (or a scheduler) should auto-promote after a confidence/age threshold
- Human can still block via Telegram or by adding a `hold` label

**Gap 2: Auto-merge with confidence scoring**
- After fix agent runs, a PR with no CRITICAL/IMPORTANT issues and passing syntax checks
  should merge itself
- Review agent needs to emit a machine-readable confidence score
- Auto-merge only when score > threshold AND no open CRITICAL issues

**Gap 3: Backlog hygiene agent**
- Periodically audit open issues against merged PRs and current codebase
- Close issues that have already been implemented
- Flag issues that are now redundant given what was built
- Prevents backlog from rotting as the system grows

### Phase 4 — Scale & Observe
> Goal: The system runs 24/7 with a daily budget, visible health metrics.

- [ ] Deploy to Railway/Fly.io (persistent process, not GitHub Actions)
- [ ] Cost dashboard — per agent, per day, trend over time
- [ ] Velocity metrics — issues closed per week, PR cycle time
- [ ] Budget auto-scaling — spend more on days with big PRs, less on idle days
- [ ] Multi-repo support

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

Personal POC built by Jordan. The goal is a system that grows like a plant:
given a daily budget, it decides what to build, builds it, and ships it.
The human sets direction (this file + Telegram) and watches it grow.

If successful, the pattern could be adapted for Robotiq (Jira + GitLab) to
automate the helpdesk → ticket → resolution pipeline for palletizer installations.
