# Foreman Project Rules

## Stack
- Python 3.11+, PyGithub, LiteLLM, PyYAML, pydantic, pytest
- Virtualenv at `.venv` — always activate before running anything

## Code Standards
- TDD: red → green → refactor. Always run full test suite after changes.
- SOLID / Clean Code (Uncle Bob). Short functions, readable like sentences.
- Clean Architecture: domain logic at center (`brain/`), adapters at edges (`llm_client.py`, `telegram_notifier.py`).
- Typed Python. No `Any` unless truly necessary.
- AI-provider agnostic — abstract behind interfaces, switching models is a config change.

## Comments & Readability
- Write comments that explain *why*, not *what* — especially for locks, async boundaries, non-obvious control flow.
- Jord reviews all code after generation. Explain in layman terms so a reviewer who knows Python but not the subtle reasoning can follow.
- Treat functions as systems: document what goes in and what comes out.

## Classes vs Functions
- Classes are for stateful things only. Stateless processes should be free functions.
- Don't wrap stateless logic in a class — use a module with functions.

## File Layout
- Constants and prompt templates at the top of the file.
- Main/public entry-point functions next.
- Private helper functions at the bottom.
- If you need to test a function, it should be public (no `_` prefix).

## Testing
- Never test private methods directly. If it needs testing, make it public or test through the public API.
- Use pydantic for LLM response validation.
- Run tests with: `source .venv/bin/activate && python -m pytest tests/brain/ -v`
- Every bug fix must include at least one regression test that would have caught the bug.

## Brain Architecture
- Brain loop: survey → council deliberation → chair decision → tool execution → journal
- Council uses N+1 LLM calls (one per agent + chair)
- Memory privacy enforced in code — agents only see own memory + shared
- All state persisted as git-committed files
- Config in `config.yml`, constitution in `PHILOSOPHY.md`
