# Research: Automated Backlog Hygiene Agent (Issue #98)

## 1. Overview
The Backlog Hygiene Agent is designed to maintain the quality and clarity of the repository's issue tracker. Its primary goals are deduplication of issues and priority scoring. This ensures the Fellowship focuses on the most impactful tasks and avoids fragmented effort.

## 2. Architecture

### A. Core Workflow
1. **Discovery**: Periodically fetch all open issues using `list_issues`.
2. **Analysis**: Process issues using an LLM to identify duplicates and assess priority.
3. **Action**:
   - Close duplicate issues with a comment referencing the original.
   - Update issue labels or metadata with priority scores.
   - Summarize changes to the Fellowship (via Telegram or a journal entry).

### B. Deduplication Logic
- **Similarity Comparison**: Use LLM embeddings or direct text comparison of titles and bodies.
- **Grouping**: Group potential duplicates and select the "canonical" issue (usually the oldest or most detailed).
- **Resolution**: Comment on the "duplicate" issue: *"Closing as a duplicate of #[Original Issue Number]. Please follow updates there."* then call `close_issue`.

### C. Priority Scoring Logic
- **Criteria**:
  - **Impact**: How many users/systems are affected?
  - **Urgency**: Is there a deadline or a blocking dependency?
  - **Effort**: Estimated complexity (Low/Medium/High).
- **Formula**: `Score = (Impact * Urgency) / Effort`.
- **Labels**: Apply labels like `priority:high`, `priority:medium`, `priority:low`.

## 3. Tooling Requirements
- **Existing Tools**:
  - `list_issues`: To fetch current backlog.
  - `close_issue`: To handle duplicates.
  - `read_file`: To check for project roadmap or philosophy (for context).
- **Recommended New Tools**:
  - `update_issue`: To modify labels, titles, or bodies of existing issues.
  - `post_issue_comment`: Specifically for issues (the current `post_comment` is PR-focused).

## 4. Implementation Steps
1. **Phase 1: Scout**: Perform a manual-trigger or weekly scan of the backlog.
2. **Phase 2: Deduplication**: Automate closing of exact/near-exact duplicates with human-in-the-loop review.
3. **Phase 3: Scoring**: Integrate LLM evaluation to suggest priority labels based on `PHILOSOPHY.md` and `VISION.md`.

## 5. Potential Challenges
- **False Positives**: Closing issues that are similar but distinct. Mitigate by having a "pending-review" label.
- **Context Window**: Large backlogs might exceed context windows. Solution: Process issues in batches or use a vector database for similarity search.

## 6. Recommended Tools & Services
- **LangChain/LlamaIndex**: For advanced RAG/Vector search if the backlog grows large.
- **GitHub Actions**: To trigger the agent on new issue creation or a schedule.
