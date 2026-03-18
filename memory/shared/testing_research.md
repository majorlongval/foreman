# Proposal: Automated Test Suite Integration

## 1. Overview
To ensure the reliability of the Fellowship's brain and enable safe autonomous operations, we must integrate an automated testing suite into our CI/CD pipeline. This will provide immediate feedback on code changes and prevent regressions.

## 2. Testing Framework: Pytest
We will standardize on **Pytest** for our testing framework. It offers a powerful, flexible syntax and supports a wide range of plugins.

### Requirements
- `pytest`: Core testing framework.
- `pytest-asyncio`: Since our brain involves asynchronous operations (LLM calls, tool execution).
- `pytest-mock`: For mocking external services and APIs.

## 3. Coverage Analysis: Coverage.py
To measure the effectiveness of our tests, we will use `coverage.py` via the `pytest-cov` plugin.

### Goals
- Target **80% minimum code coverage** for the `brain/` directory.
- Generate HTML reports for local debugging and XML reports for CI integration.

## 4. CI/CD Integration (GitHub Actions)
We will implement a GitHub Actions workflow (`.github/workflows/tests.yml`) that triggers on:
- Every Push to `main`.
- Every Pull Request.

### Workflow Steps
1. **Environment Setup**: Install Python and dependencies from `requirements.txt`.
2. **Test Execution**: Run `pytest --cov=brain/ --cov-report=xml`.
3. **Coverage Check**: Use a tool like `codecov` or a simple script to fail the build if coverage is below the threshold.
4. **PR Feedback**: Automatically comment on PRs with the coverage summary and test results.

## 5. Implementation Plan
1. **Standardize Tests**: Ensure all files in `tests/brain/` are compatible with Pytest discovery rules.
2. **Configure Pytest**: Create/Update `pyproject.toml` with pytest and coverage settings.
3. **Setup GitHub Action**: Create the workflow file to automate execution.
4. **Enforce Policy**: Update repository settings to require passing tests before merging.

## 6. Future Enhancements
- **Auto-merging**: Once the CI pipeline is stable, enable auto-merging for PRs from trusted agents that pass all tests and meet coverage requirements.
- **Integration Tests**: Expand `tests/brain/test_integration.py` to cover end-to-end agent loops with mocked LLM responses.
