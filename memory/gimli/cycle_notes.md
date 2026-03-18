# Gimli's Cycle Notes

## Task: Issue #124 - CI/CD Workflow
Implemented the CI/CD pipeline by updating `pyproject.toml` and `.github/workflows/lint.yml`.
The new workflow uses `reviewdog/action-ruff` and `reviewdog/action-mypy` to provide inline PR annotations for linting and type errors.

- Updated `pyproject.toml` with `ruff` and `mypy` configurations.
- Replaced the manual lint steps in `lint.yml` with Reviewdog actions.
- Opened PR #126.
