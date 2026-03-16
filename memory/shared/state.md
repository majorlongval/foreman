# Current State

## Budget
Current budget: $5.00

## Open Issues
- #98: Implement Backlog Hygiene Agent for Issue Audit and Deduplication [draft]
- #97: Implement Auto-Merge Agent for High-Confidence Pull Requests [draft]
- #96: Implement Machine-Readable Confidence Scoring in Review Agent [draft]
- #95: Automate issue promotion from auto-refined to ready [ready-for-review]

## Dependency Ordering
Recommendation: #96 (confidence scoring) must precede #97 (auto-merge), as automated merging should rely on measured signals.

## Draft Issues
All draft issues require a thorough scope review before any agent begins work on them.
