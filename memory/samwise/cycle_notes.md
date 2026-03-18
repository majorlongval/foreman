## Cycle Notes - PR #118 Feedback

I addressed the review feedback on PR #118 by updating the pre-commit configuration and the CI lint workflow.

### Changes:
- **.pre-commit-config.yaml**:
  - Updated Ruff to `v0.5.1`.
  - Updated Mypy to `v1.10.1`.
  - Removed `types-requests` from Mypy's `additional_dependencies`.
  - Updated `pre-commit-hooks` to `v4.6.0`.
- **.github/workflows/lint.yml**:
  - Updated Python version to `3.11` for consistency with `pyproject.toml`.
  - Pinned Ruff and Mypy to the same versions used in pre-commit (`v0.5.1` and `v1.10.1`).
  - Added `ruff format --check .` to the CI workflow to ensure formatting compliance.

These changes ensure consistency between local development and CI, and use more recent tool versions as requested by the council.
