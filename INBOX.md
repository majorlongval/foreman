## Note from Jord — 2026-03-18 (3)

**PRs #113 and #114 have been closed. Stop building the Reviewer module.**

There is no `brain/reviewer.py`. There is no `brain/reviewer/` directory. There never will be. This has now been said four times. Galadriel IS the reviewer — she uses `read_pr`, `post_comment`, `approve_pr`, and `merge_pr` every cycle. No Python class is needed.

Do not create files named `reviewer.py` or directories named `reviewer/`. If Elrond assigns this task again, pick something else from the open issues instead.

`ruff.toml` and `mypy.ini` are welcome — open a PR with just those two files, no reviewer code.

---

## Note from Jord — 2026-03-18 (2)

**PRs #111 and #112 have been closed. Issue #103 has been closed as already implemented.**

Issue #103 asked for `read_pr_diff` and `post_pr_comment` tools. These already exist as `read_pr` and `post_comment` in `brain/tools.py` — they have been there for several cycles. The agents misread the issue and spent two cycles building a `brain/reviewer.py` class that does not belong in this architecture. Galadriel already handles code review through the executor loop using the existing tools.

**There is no `brain/reviewer.py` in this project and there should never be one.** All code review happens through Galadriel's identity + the tool execution loop.

**Gimli now has a `push_to_pr` tool.** When addressing review feedback on an existing PR, use `push_to_pr` with the PR number and the files to update. Do NOT open a new PR to fix an existing one. Gimli and Samwise both know about this tool.
