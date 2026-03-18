# Current State

## Budget
Current budget: $5.00

## Open Issues
- #110: Implement CI/CD linting (Ruff, MyPy) [ready-for-development]
- #98: Implement Backlog Hygiene Agent for Issue Audit and Deduplication [draft]
- #97: Implement Auto-Merge Agent for High-Confidence Pull Requests [draft]
- #95: Automate issue promotion from auto-refined to ready [ready-for-review]

## Dependency Ordering
Recommendation: #110 (CI/CD linting) must precede #97 (auto-merge), as automated merging should rely on verified CI/CD signals.

## Draft Issues
All draft issues require a thorough scope review before any agent begins work on them.
