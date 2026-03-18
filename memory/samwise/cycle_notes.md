### Cycle Notes - PR #121 Feedback

I have addressed the review feedback for PR #121 by:
1.  **Implementing String Normalization**: Added a `_normalize` method in `Deduplicator` to strip punctuation and convert to lowercase in `calculate_similarity`.
2.  **Configurable Thresholds**: Modified `Deduplicator` to accept `title_weight` and `body_weight` as parameters, moving away from hardcoded values.
3.  **Improved Code Quality**: Refactored `find_potential_duplicates` for better readability, added type hints, and ensured proper import ordering and docstrings to address linting issues.
4.  **Expanded Test Suite**: Added test cases for missing/empty issue bodies, configurable weights, and verified default threshold behavior with "real-world" examples.

All changes pushed to the PR branch.
