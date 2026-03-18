# Logic for Automated Issue Promotion (Issue #95)

## 1. Goal
To automate the transition of issues from the `auto-refined` state to the `ready` state (the implementation queue), reducing human overhead while maintaining quality and ensuring the implementation agents (Gimli) have clear instructions.

## 2. Context
As defined in `VISION.md`, the issue lifecycle includes a transition from `auto-refined` (the output of an agent refining a `draft` or `needs-refinement` issue) to `ready`. Currently, this transition is manual or requires direct human intervention. This proposal defines the automated logic for this promotion.

## 3. Promotion Logic

### A. Automatic Promotion (The "Fast Lane")
Issues meeting the following criteria are promoted to `ready` automatically by the Backlog Hygiene or a dedicated Promotion Agent:
1. **Source State**: Must have the `auto-refined` label.
2. **Mandatory Sections**: The issue body must contain valid content for:
   - **Context/Background**: Why this is being done.
   - **Task Details**: What exactly needs to be implemented.
   - **Deliverables**: Clear list of expected files/outputs.
   - **Acceptance Criteria**: How the Critic (Galadriel) will verify the work.
3. **Complexity & Risk**:
   - The issue must be labeled as `scope:small` or `priority:low`.
   - The issue must not modify "protected" files (e.g., `brain/loop.py`, `brain/executor.py`, `config.yml`) unless it's a documentation-only change.
4. **Agent Confidence**: If the Refiner agent provides a confidence score (0-1.0), it must be above `0.9`.

### B. Consensus Promotion (The "Fellowship Lane")
Issues that do not meet the "Fast Lane" criteria but are still valuable can be promoted if:
1. **Peer Review**: At least one other agent (Gandalf or Samwise) provides a positive "thumbs up" or "support" comment after a secondary review.
2. **Time-based Promotion**: The issue has remained in `auto-refined` for more than 24 hours without any `blocked`, `needs-human`, or negative comments.

### C. Human Intervention (The "Council Lane")
Issues are flagged with `needs-human` and excluded from automated promotion if:
1. **Ambiguity**: The issue body is less than a certain character threshold (e.g., < 200 chars) after refinement.
2. **High Risk**: Labeled as `priority:high` or `scope:large`.
3. **Conflict**: There are overlapping issues identified by the Backlog Hygiene Agent (Issue #98).

## 4. Operational Steps (Implementation via #119)
The Backlog Hygiene Agent or a dedicated Promotion script will:
1. **Fetch**: List all issues with `auto-refined`.
2. **Analyze**: Evaluate against the checklist (LLM-based evaluation of the body quality).
3. **Update**:
   - On success: Remove `auto-refined`, add `ready`.
   - On failure: Maintain `auto-refined` and add a comment explaining missing requirements.
   - On high-risk/stale: Add `needs-human`.

## 5. Metrics for Success
- **Velocity**: Number of issues moved to `ready` per cycle without human touch.
- **Accuracy**: Percentage of automatically promoted issues that are completed and merged without rework.
