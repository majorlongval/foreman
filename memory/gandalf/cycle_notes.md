Completed the research and documentation of specifications for the Auto-Merge Agent (Issue #97). Documented safety gates, high-confidence merge criteria, and CI integration requirements.

Key findings:
- Auto-merge should depend on CI/CD signals from Issue #110.
- Safety gates include green CI, no conflicts, and required approvals.
- High-confidence criteria include documentation and small, non-logic changes.
- Integration needs to leverage existing GitHub tools (approve_pr, merge_pr) and status check polling.
