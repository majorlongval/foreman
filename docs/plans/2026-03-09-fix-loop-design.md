# Fix Loop & Auto-Merge — Design

## Goal

Close the review loop so PRs can self-heal and auto-merge for trivial tasks. After the implement agent opens a PR, the review agent reviews it, a fix agent addresses any issues, and if the code comes back clean it merges automatically.

## Architecture

Three pieces:

1. **Review agent upgrade** (modify `review_agent.py`)
2. **Fix agent** (new `fix_agent.py`)
3. **GitHub Actions wiring** (new `fix_agent.yml`, modify `review_agent.yml`)

## The Full Cycle

```
implement → PR → review (Gemini 3.1 Flash) → issues found?
  YES → fix agent → push fixes → review again → issues found?
    YES → fix agent (cycle 2) → push → review again → issues found?
      YES → notify human, add needs-human label, stop
      NO → pass 2 (Gemini 3 Pro) → clean? → auto-merge (if eligible)
    NO → pass 2 (Gemini 3 Pro) → clean? → auto-merge (if eligible)
  NO → pass 2 (Gemini 3 Pro) → clean? → auto-merge (if eligible)
```

## Review Agent Upgrades

### Two-pass review
- Pass 1: Gemini 3.1 Flash (cheap, always runs)
- Pass 2: Gemini 3 Pro (confirmation, only runs if Pass 1 found zero critical/important issues)
- Both passes use the same review prompt, different models

### Structured output
- Review prompt outputs JSON alongside markdown review
- Programmatically parseable: verdict, issue count by severity, affected files
- Markdown review still posted as human-readable PR comment

### Auto-merge logic
- After Pass 2 returns APPROVE + zero critical/important issues:
  - Check for `auto-merge-eligible` label on PR or linked issue
  - If present → `pr.merge()`, post comment, Telegram notification
  - If absent → post "Ready to merge" comment, Telegram notification, human merges
- Without `auto-merge-eligible`, behavior is same as today (human merges)

### Cycle tracking
- Count FOREMAN review comments on PR to determine cycle number
- If cycle count >= 2 fix attempts → don't trigger fix agent, notify human instead
- Add `needs-human` label when escalating

## Fix Agent (new file: fix_agent.py)

### Trigger
- GitHub Action on `pull_request_review` event
- Script checks: is it a FOREMAN review? Does it have CRITICAL/IMPORTANT issues? Under retry limit?

### What it does
1. Read the review comment body from the PR
2. Parse which files have issues and what the issues are
3. Fetch those files from the PR branch (not main)
4. Send each file + its review comments to LLM: "make minimal fixes"
5. Syntax check (ast.parse) before pushing
6. Push fixed files to the same PR branch
7. Post PR comment: "Applied fixes for: [list of issues addressed]"

### What it does NOT do
- Re-plan or re-implement from scratch
- Touch files not mentioned in the review
- Create new branches or new PRs
- Make "improvements" beyond what the review asked for

### Fix prompt
Instructs LLM to make MINIMAL changes addressing only the review comments. No refactoring, no reorganization, no improvements. Output complete fixed file content only.

### Model
Gemini 3.1 Flash (fixes are small and targeted)

### Cost ceiling
$1.00 per run (fixes should cost cents — if it's spending more, something is wrong)

## GitHub Actions Wiring

### review_agent.yml (modified)
- Add `contents: write` permission for auto-merge
- No trigger changes needed (already triggers on `opened`, `synchronize`)

### fix_agent.yml (new)
- Trigger: `pull_request_review` (when a review is submitted)
- Permissions: `contents: write`, `pull-requests: write`, `issues: write`
- Script handles filtering (is it FOREMAN review? has issues? under limit?)

### Label-based coordination
- `reviewed` — prevents review agent from re-reviewing (existing)
- `fixing` — prevents fix agent from double-fixing during a cycle
- `needs-human` — escalation: fix cycles exhausted
- `auto-merge-eligible` — opt-in for auto-merge (set per issue/PR)

## Safety Rails

1. **Auto-merge is opt-in** — requires `auto-merge-eligible` label. Without it, clean reviews just notify you.
2. **2 fix cycle max** — tracked by counting FOREMAN reviews. After 2 fixes, escalate to human.
3. **Fix scope guard** — only touches files mentioned in the review.
4. **Syntax check** — ast.parse before pushing, same as implement agent.
5. **Cost ceilings** — fix agent: $1, review agent: $1.
6. **Label locks** — `reviewed` and `fixing` labels prevent races between agents.

## Models

| Role | Model | Why |
|------|-------|-----|
| Review pass 1 | Gemini 3.1 Flash | Cheap, catches obvious issues |
| Review pass 2 | Gemini 3 Pro | Confirmation before auto-merge |
| Fix generation | Gemini 3.1 Flash | Fixes are small and targeted |

## What This Does NOT Include

- Confidence scoring as a numeric percentage (binary: issues or no issues)
- Human approval via Telegram reply (just notification — merge via Brain or GitHub)
- Changes to the implement agent
- Changes to the Brain
