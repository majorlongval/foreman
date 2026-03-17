## What is this file

This is your inbox. I (Jord) write notes here when I want to tell you something between cycles. You will see this at the start of every council. Once you have read it, the system clears it automatically — so each message is delivered once.

If you want to write back to me, create a file called OUTBOX.md at the root of the repo. I will read it and clear it. Use it to ask questions, flag decisions you want my input on, or tell me something I should know.

---

## Note 1 — Push conflict

The last memory commit failed because I was pushing code at the same time your cycle ran. No data was lost. The brain_loop workflow now does a rebase before pushing so this should not happen again.

---

## Note 2 — Diversity in the council

Looking at the last council: all four of you said essentially the same thing. That is a waste. Each of you should argue from your own domain exclusively. Gandalf explores and redirects. Gimli builds concrete things. Galadriel raises risks and gaps. Samwise flags what is rotting. Diverse perspectives open up parallel workstreams — four agents voting on the same thing is not a council, it is an echo chamber.

---

## Note 3 — PR review tooling

Galadriel needs to be able to review PRs. Right now she can see a PR exists but cannot read its content. Please design and implement the following:

- A tool for agents to read a PR (title, description, changed files, diff)
- A tool to post a comment on a PR
- The survey should include recent comments on open PRs so Gimli can see Galadriel's feedback and act on it

Follow the existing patterns in brain/tools.py. Use TDD. Gimli builds, Galadriel defines what she needs to do her job, Gandalf checks if anything is missing, Samwise makes sure it is tested and documented.

---

## Note 4 — Recent failures and what was fixed

The last two cycles had errors. Samwise's response was truncated mid-JSON and failed to parse. Galadriel hit her token limit and produced a similarly broken response. Both issues have been fixed on my end: LLM calls now enforce a structured JSON schema, and the token budget for each agent was doubled. You do not need to do anything — I am telling you so you understand why the previous cycles look incomplete in the journal.

---

## Note 5 — Cut the prelude

When giving your perspective in council, lead with your actual position. Do not open with "I agree with [previous agent]" or restate what they already said. The chair reads all perspectives — repetition wastes tokens and buries your real contribution. Say something new or say nothing.
