## Note from Jord — 2026-03-18

**PR #109 has been closed.** It contained only empty `__init__.py` placeholder files in a `lib/foreman/reviewer/` directory that does not exist in this project. This is a hallucinated structure from earlier cycles. All real code lives in `brain/`. Issue #103 is still open — implement reviewer tooling there, inside `brain/`, following existing conventions.

**Gimli cannot push to existing PRs.** The `create_pr` tool creates a *new* branch and PR. There is no tool to push additional commits to an existing PR branch. Do not assign Gimli tasks like "push commits to PR #109" — he has no way to do that. Gimli's job is to **open new PRs** with working code using `create_pr`. If you want to iterate on an existing PR, close it and have Gimli open a fresh one.

**Elrond's model has been switched to gemini-3-flash-preview.** The pro model cost $0.35 per cycle which is unsustainable. Flash is the same model the workers use and is sufficient for orchestration.
