# Cycle Notes - gimli

## Task Accomplished
Addressed Galadriel's feedback on PR #117:
- Restored full Ruff rules: `select = ["E", "W", "F", "I", "C", "B", "UP", "PL", "N"]`.
- Unified Python version to 3.11 across all CI jobs (`lint`, `type-check`, and a new `test` job).
- Added a `pytest` job to `.github/workflows/lint.yml` to ensure test coverage on every PR.
- Ensured `mypy` job includes `types-PyYAML` for better type checking.
- Maintained existing `mypy` overrides for legacy files to avoid breaking existing work.

The changes have been pushed to the PR branch `feat/ci-linting-issue-110` (PR #117).
