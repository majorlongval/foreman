### Cycle Notes - PR #121 Feedback

I have addressed the review feedback for PR #121 by:
1.  **Implementing String Normalization**: Added a `_normalize` method in `Deduplicator` to strip punctuation and convert to lowercase in `calculate_similarity`.
2.  **Configurable Thresholds**: Modified `Deduplicator` to accept `title_weight` and `body_weight` as parameters, moving away from hardcoded values.
3.  **Improved Code Quality**: Refactored `find_potential_duplicates` for better readability, added type hints, and ensured proper import ordering and docstrings to address linting issues.
4.  **Expanded Test Suite**: Added test cases for missing/empty issue bodies, configurable weights, and verified default threshold behavior with "real-world" examples.

All changes pushed to the PR branch.

### Cycle Notes - Backlog Consolidation

Consolidated the requirements of Issue #122 ("Automate issue promotion") into Issue #98 ("Backlog Hygiene Agent") within `shared/state.md`. 
- Updated #98's scope to include automated issue promotion from 'auto-refined' to 'ready'.
- Moved #122 to the "Closed Issues" section in `shared/state.md`.
- Officially closed Issue #122 on GitHub with a reference to #98.
