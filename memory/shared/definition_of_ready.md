# Definition of Ready (DoR)

This document defines the criteria that an issue must meet to be moved from **auto-refined** to **ready**. An issue is "Ready" when it contains enough information for any agent to begin work immediately without seeking further clarification from the Council or Jord.

## Criteria for "Ready" Status

An issue is considered **Ready** if it satisfies the following checklist:

### 1. Clear Title and Problem Statement
- The title is descriptive of the work to be done.
- The description clearly explains *what* needs to be changed and *why* (the motivation).

### 2. Explicit Acceptance Criteria (AC)
- There is a list of verifiable outcomes.
- Each AC can be tested (manually or automatically).
- The "Definition of Done" for this specific task is clear.

### 3. Technical Context and Scope
- Relevant files, classes, or modules are identified.
- The scope is bounded: it is clear what is *out of scope* to prevent scope creep.
- Any architectural constraints (e.g., following Hexagonal Architecture, SOLID) are noted if they are non-obvious.

### 4. Testability (TDD Alignment)
- The issue suggests a testing strategy (e.g., "Must include unit tests for the new tool in `tests/brain/`").
- It identifies potential edge cases to be covered.

### 5. Dependency and Blocker Check
- All external dependencies (e.g., a specific API key, a previous PR being merged) are identified.
- If the issue is blocked, it cannot be marked as "Ready".

### 6. Alignment with Philosophy
- The proposed change aligns with the `PHILOSOPHY.md` (e.g., no `Any` types, provider-agnostic).

## Process

1. **Auto-Refinement**: An agent or process creates/updates an issue with initial details.
2. **Review**: A second agent (or the Council) reviews the issue against this DoR.
3. **Transition**: Once all criteria are met, the label is changed to `ready`.

*Note: For small, trivial fixes, these criteria can be applied lightly. For core engine changes or new features, they must be strictly followed.*
