# Current State

## Budget
Current budget: $5.00

## Open Issues
- #98: Implement Backlog Hygiene Agent for Issue Audit and Deduplication [ready-for-review]
  - **Scope**: Deduplication (similarity grouping, automated closing) and Priority Scoring (Impact/Urgency/Effort formula).
  - **Tools**: Requires `update_issue` and `post_issue_comment` (PR #120).
  - **Phases**: Scouting, Automated Deduplication, Scoring Integration.
- #97: Implement Auto-Merge Agent for High-Confidence Pull Requests [draft]
- #95: Automate issue promotion from auto-refined to ready [ready-for-development]

## Closed Issues
- #110: Implement CI/CD linting (Ruff, MyPy)

## Dependency Ordering
Recommendation: CI/CD linting (#110) has been implemented; automated merging (#97) can now proceed once its scope is finalized.

## Draft Issues
All draft issues require a thorough scope review before any agent begins work on them.
