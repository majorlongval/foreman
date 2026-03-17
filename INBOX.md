## Note from Jord — 2026-03-17

**Issue #108 has been closed.** Pydantic validation (`AgentResponse`, `ChairResponse`) was already implemented in `brain/council.py`. You have been asking for something that already exists.

**Two real bugs have been fixed:**

1. **Deliberation truncation** — `max_tokens` for each agent's deliberation was 2048, which was too tight for verbose responses (Galadriel, this means you). It has been raised to 4096. Your JSON was being cut off mid-string, causing the "Unterminated string" errors you kept seeing.

2. **Chair JSON parsing** — The `phases` field (a list of lists) was sometimes causing Gemini to emit unquoted object keys. `_fix_json` now handles this case.

**You do not need to open issues or write plans about JSON schema hardening.** The foundation is solid. Focus on building real features — Issue #103 (PR Observation) is still open and waiting.
