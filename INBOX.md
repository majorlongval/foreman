## What is this file

This is your inbox. I (Jord) write notes here when I want to tell you something between cycles.

**These notes are directives, not suggestions.** Treat them with the same weight as PHILOSOPHY.md. The chair must act on inbox notes before anything else this cycle.

If you want to write back to me, create OUTBOX.md at the repo root.

---

## Note 1 — Chair failure last cycle

Gandalf was chair and the decision step failed with a truncated JSON error. The response hit the token limit mid-way through writing the assignments. This has been fixed — the chair now has a 4096 token budget instead of 2048. No data was lost. The cycle completed with no agent actions taken.

---

## Note 2 — Reminder: you all act now

Each agent now runs their own tool-use loop every cycle. The chair assigns a specific task to each of you by name. When deliberating, propose something you can concretely do with the available tools this cycle. Vague proposals waste the assignment.

Available tools: read_file, create_issue, create_pr, read_pr, post_comment, approve_pr, read_memory, write_memory, send_telegram, check_budget, list_issues, list_prs.
