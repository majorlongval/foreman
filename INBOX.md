## What is this file

This is your inbox. I (Jord) write notes here when I want to tell you something between cycles.

**These notes are directives, not suggestions.** Treat them with the same weight as PHILOSOPHY.md. The chair must act on inbox notes before anything else this cycle.

If you want to write back to me, create OUTBOX.md at the repo root.

---

## Note 1 — Last cycle had a push failure

The memory commit at the end of the last cycle failed with a merge conflict in the cost tracking file. Two cycles ran close together and both tried to write to the same file at the same time. This has been fixed on my end — the cost files now use a union merge strategy so concurrent writes no longer conflict. You do not need to do anything about this.

---

## Note 2 — Architecture change: you all act now

The council architecture has changed. Previously only the chair executed actions. Starting this cycle, the chair assigns a specific task to each of you by name, and every agent runs their own tool-use loop.

This means:
- In deliberation, propose something concrete that **you specifically** can do with the available tools
- The chair should assign tasks that can run independently — avoid assigning the same resource to two agents
- If you have nothing useful to do this cycle, say so — an empty task is better than a vague one

The available tools are: read_file, create_issue, create_pr, read_pr, post_comment, approve_pr, read_memory, write_memory, send_telegram, check_budget, list_issues, list_prs.
