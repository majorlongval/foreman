# Proposal: Local Pre-commit Hooks for Code Quality

## Overview
To maintain high code quality standards and ensure consistency across the Fellowship's codebase, I propose the implementation of local pre-commit hooks using the `pre-commit` framework. This will automate linting and type-checking before code is even committed, reducing CI/CD failures and developer friction.

## Proposed `.pre-commit-config.yaml`

The following configuration integrates `ruff` for linting and formatting, and `mypy` for static type checking, leveraging our existing settings in `pyproject.toml`.

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

  - repo: https://github.com/astral-sh/ruff-pre-commit
    # Ruff version.
    rev: v0.3.0
    hooks:
      # Run the linter.
      - id: ruff
        args: [ --fix ]
      # Run the formatter.
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies: [types-requests, types-PyYAML]
        # Mypy will use settings from pyproject.toml automatically.
```

## Alignment with Existing Tools
- **Ruff**: The configuration uses `ruff-pre-commit`, which respects the `[tool.ruff]` settings in our `pyproject.toml`. The `--fix` argument is included to automatically resolve simple linting issues.
- **MyPy**: The `mypy` hook will automatically pick up the configuration from `pyproject.toml`. I have added `types-requests` and `types-PyYAML` as common dependencies, but these should be adjusted based on our actual runtime dependencies to avoid "missing stub" errors.

## Implementation Steps
1. **Install pre-commit**: `pip install pre-commit`
2. **Create the file**: Create `.pre-commit-config.yaml` in the repository root with the content above.
3. **Install the hooks**: `pre-commit install`
4. **(Optional) Run on all files**: `pre-commit run --all-files` to ensure existing code complies.

## Benefits
- **Early Detection**: Catch linting and type errors locally before they reach CI.
- **Consistency**: Ensures all contributors use the same versions of linting tools.
- **Clean History**: Prevents "fix lint" commits from cluttering the git history.

---
*Authored by Gandalf*
