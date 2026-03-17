## What is this file

This is your inbox. I (Jord) write notes here when I want to tell you something between cycles.

**These notes are directives, not suggestions.** Treat them with the same weight as PHILOSOPHY.md. The chair must act on inbox notes before anything else this cycle.

If you want to write back to me, create OUTBOX.md at the repo root.

---

## URGENT — You are building things that already exist

I have closed PR #102 and PR #104. Both were building a tool execution engine in `src/` and `lib/`. That code already exists. You have been wasting cycles.

Here is the actual structure of this repository:

```
brain/
  loop.py        — the main cycle (survey → council → execute → journal)
  council.py     — agent deliberation + chair decision
  executor.py    — tool-use execution loop (THIS IS WHAT YOU WERE TRYING TO BUILD)
  tools.py       — all tools: read_file, create_issue, create_pr, read_memory,
                   write_memory, send_telegram, check_budget, list_issues,
                   list_prs, read_pr, post_comment, approve_pr
  survey.py      — gathers GitHub state, budget, memory, PR comments
  memory.py      — scoped memory with privacy enforcement
  cost_tracking.py — JSONL cost persistence
  config.py      — typed config loader
memory/
  shared/        — costs, journal, decisions, incidents (all written each cycle)
  gandalf/
  gimli/
  galadriel/
  samwise/
```

**Do not create files in src/, lib/, or any other new directory.** All new code goes in `brain/`.

The tool execution engine is working. You used it this cycle to call `list_prs` and `list_issues`. You do not need to rebuild it.

**What you should actually be doing:** Use `read_pr` to review open PRs, use `post_comment` to leave feedback, use `create_issue` to propose real features that are missing. Read the existing code with `read_file` before deciding what to build next.

Start by running `read_file` on `brain/tools.py` and `brain/executor.py` so you know what you actually have.
