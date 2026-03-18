# Research: Issue Promotion Automation Architecture & Safety

## Overview
This document outlines the architecture and safety requirements for automating the promotion of GitHub issues from `auto-refined` to `ready-for-development`, as part of the Backlog Hygiene Agent's responsibilities.

## 1. Architecture

### A. Promotion Workflow
1.  **Scanning**: The Backlog Hygiene Agent (BHA) periodically lists open issues filtering for the `auto-refined` label.
2.  **Retrieval**: For each candidate, the BHA reads the issue body and all existing comments to build full context.
3.  **Evaluation**: The BHA compares the issue against a standardized **Definition of Ready (DoR)**.
4.  **Decision**:
    *   **Pass**: If DoR is met, the BHA invokes the promotion action.
    *   **Fail**: If DoR is not met, the BHA posts a comment detailing missing requirements and keeps the `auto-refined` label (or adds a `needs-clarification` label).
5.  **Promotion Action**:
    *   Remove `auto-refined` label.
    *   Add `ready-for-development` label.
    *   Post a "Promotion Summary" comment.

### B. Definition of Ready (DoR) Criteria
To be promoted, an issue must have:
*   **Clear Title**: Descriptive and prefixed (e.g., `feat:`, `fix:`, `chore:`).
*   **Context/Problem Statement**: Why is this being done?
*   **Proposed Solution**: High-level technical or functional approach.
*   **Acceptance Criteria (AC)**: A checklist of what "done" looks like.
*   **No Blockers**: No open "Question" labels or unresolved threads in comments.

### C. Required Tooling
Currently, the brain lacks a direct `update_issue` tool. The following additions are required:
*   `update_issue(issue_number, labels_add: List[str], labels_remove: List[str])`: To manage state transitions.
*   `post_issue_comment(issue_number, body: str)`: To provide the audit trail (distinct from PR comments).

## 2. Safety Requirements

### A. Guardrails
*   **Rate Limiting**: The BHA is restricted to promoting a maximum of 5 issues per cycle to prevent "runaway automation" if a prompt or logic error occurs.
*   **Confidence Threshold**: The agent must explicitly state its confidence level (0-1). Promotions only occur if confidence > 0.85.
*   **Negative Feedback Loop**: If a human or another agent reverts a promotion (removes `ready-for-development`), the BHA must log this as a "Promotion Failure" in `memory/shared/incidents/` and analyze the reason to update its internal heuristic.

### B. Audit & Transparency
*   **Promotion Summary**: Every promotion must include a comment on the issue:
    > "### 🤖 Issue Promoted to Ready
    > This issue meets the Definition of Ready.
    > - [x] Acceptance Criteria defined.
    > - [x] No unresolved blockers.
    > - [x] Implementation path clear."
*   **Shared Log**: All promotion actions must be appended to `memory/shared/backlog_hygiene_log.md`.

### C. Permissioning
*   **Role-Based Access**: Only agents with the `backlog-manager` or `critic` role should be permitted to use the `update_issue` tool for promotion purposes.

## 3. Implementation Roadmap
1.  Implement `update_issue` and `post_issue_comment` tools (Issue #119).
2.  Define the formal DoR in `memory/shared/standards/definition_of_ready.md`.
3.  Deploy the BHA with "Dry Run" mode (posts comments but doesn't change labels) for 3 cycles.
4.  Enable full automation after review of Dry Run results.
