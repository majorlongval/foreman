# Research Document: CI/CD Integration for Ruff, MyPy, and Reviewdog

## Overview
As per Issue #110, this document details the proposed GitHub Actions configuration to automate linting, static type checking, and automated PR reviews using Reviewdog. This setup ensures high code quality by providing inline feedback on Pull Requests.

## Proposed Tools

### 1. Ruff
- **Purpose**: Fast Python linter and formatter. Replaces Flake8, Isort, and Black with a single tool.
- **Benefits**: Extremely fast, extensive rule set, and auto-fixing capabilities.

### 2. MyPy
- **Purpose**: Static type checker for Python.
- **Benefits**: Catches type errors before runtime, ensuring the codebase remains robust as it scales.

### 3. Reviewdog
- **Purpose**: Integrates linting tools with GitHub Pull Requests.
- **Benefits**: Comments directly on the diff in Pull Requests, making it easy for developers to see and address issues without leaving the PR interface.

## GitHub Actions Configuration

The following YAML configuration should be added to `.github/workflows/lint.yml`. It is triggered on every Pull Request and on the `main` branch.

```yaml
name: Lint and Type Check

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    name: runner / ruff
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: ruff
        uses: reviewdog/action-ruff@v1
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          # Change reviewdog reporter if needed [github-pr-check, github-check, github-pr-review]
          reporter: github-pr-review
          # Filter mode for reviewdog
          filter_mode: added
          # Fail the job if issues are found
          fail_on_error: true

  type-check:
    name: runner / mypy
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install mypy
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - name: mypy
        uses: reviewdog/action-mypy@v0
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          reporter: github-pr-review
          filter_mode: added
          fail_on_error: true
          # Optional: point to specific directory
          # mypy_flags: "brain/"
```

## Recommended Configuration Files

To ensure consistent behavior, we should add a `pyproject.toml` file to the root directory.

### pyproject.toml
```toml
[tool.ruff]
# Target Python version
target-version = "py311"
# Same as Black.
line-length = 88
indent-width = 4

[tool.ruff.lint]
# Enable Pyflakes (`F`) and a subset of the pycodestyle (`E`) codes by default.
# Unlike Flake8, Ruff doesn't enable pycodestyle warnings (`W`) or
# McCabe complexity (`C901`) by default.
select = ["E4", "E7", "E9", "F"]
ignore = []

# Allow fix for all enabled rules (when `--fix`) is provided.
fixable = ["ALL"]
unfixable = []

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true
no_implicit_optional = true
strict_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
warn_unreachable = true

[[tool.mypy.overrides]]
module = "github.*"
ignore_missing_imports = true
```

## Implementation Plan

1. **Create `pyproject.toml`**: Define rules and settings for Ruff and MyPy.
2. **Setup Secrets**: Ensure `GITHUB_TOKEN` is available to the workflow (default in GHA).
3. **Deploy `.github/workflows/lint.yml`**: Add the workflow file to the repository.
4. **Validation**: Test the workflow by opening a PR with intentional linting/typing issues.

## Conclusion
Integrating these tools via Reviewdog will streamline the review process and maintain high standards for the Foreman codebase.
