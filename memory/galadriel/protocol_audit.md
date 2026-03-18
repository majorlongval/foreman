# Structural Audit: PR Reviewer Protocol for Automation

This audit identifies specific logic gates from the `shared/pr_reviewer_protocol.md` that can be automated by the new Reviewer module.

## 1. Programmatically Verifiable Gates

### A. Functional Correctness
- **Gate**: PR addresses a linked issue.
- **Automation Strategy**: Parse the PR body for "Closes #", "Fixes #", or similar keywords and verify the issue exists.

### B. Testing & Validation
- **Gate**: All existing tests pass.
- **Automation Strategy**: Trigger and monitor the CI test suite (e.g., `pytest`).
- **Gate**: New tests for new functionality.
- **Automation Strategy**: Analyze the file diff for new files in `tests/` or modifications to existing test files.

### C. Code Quality
- **Gate**: Descriptive and consistent naming / Readability.
- **Automation Strategy**: Integrate static analysis tools (e.g., `pylint`, `flake8`) for basic style enforcement.
- **Gate**: Performance bottlenecks.
- **Automation Strategy**: Use static analysis tools to flag complex nested loops or lack of caching in known hot paths.

### D. Documentation & Memory
- **Gate**: `cycle_notes.md` updated.
- **Automation Strategy**: Check if the PR file list includes a path matching `memory/*/cycle_notes.md`.
- **Gate**: PR description clear about "What" and "Why".
- **Automation Strategy**: LLM-based verification or regex matching for section headers in the PR body.

## 2. Semi-Automated / LLM-Assisted Gates

### A. Architecture & Design
- **Gate**: Modular and reusable logic.
- **Automation Strategy**: LLM scan of the diff against architectural principles defined in `shared/architecture.md`.
- **Gate**: Scouting evaluation.
- **Automation Strategy**: Search for "Scouting" section in PR description or memory files; flag if missing.

## 3. Technical Foundation for Gimli's Module

The `brain/reviewer.py` module should implement a `Reviewer` class with the following entry points:
- `check_metadata()`: Validates PR description, linked issues, and memory updates.
- `check_tests()`: Validates test coverage and execution status.
- `check_static_analysis()`: Runs linting and complexity checks.
- `check_architecture_alignment()`: (LLM-assisted) checks for scouting and modularity.

## 4. Proposed Integration Path
1. **Phase 1**: Metadata & File presence (Direct automation).
2. **Phase 2**: Static analysis integration (Subprocess/Tool based).
3. **Phase 3**: LLM-assisted logic gate evaluation.
