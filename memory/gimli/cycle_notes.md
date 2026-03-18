# Backlog Hygiene Agent Cycle Notes

## Accomplishments
- Created branch `feat/backlog-hygiene`.
- Implemented `brain/hygiene.py` with the `Deduplicator` class using Jaccard similarity for issue titles and bodies.
- Implemented `tests/brain/test_hygiene.py` with unit tests for the deduplication logic.
- Included a placeholder/note for future research on issue promotion automation (triggers like labels, reactions, or linked PRs).

## Notes on Research
Issue promotion automation could be triggered by:
- Specific labels (e.g., 'high-priority', 'promoted').
- Threshold of reactions (e.g., 5+ 👍).
- Mentions in discussions or linked PRs.
- Stale issues with high engagement.

## Next Steps
- Integrate the `Deduplicator` with the existing `list_issues` tool.
- Explore using embeddings for more advanced similarity checks.
- Formalize the promotion automation triggers and implementation.
# Cycle Notes - PR #120 Cleanup

## Task
Fix linting errors and clean up the tool list docstrings in brain/tools.py within PR #120.

## Accomplishments
- Cleaned up the docstring of `brain/tools.py` by removing the manually maintained tool list and replacing it with a concise summary.
- Removed unused `GithubException` import to fix linting errors.
- Fixed long lines in `TOOL_SCHEMAS` by wrapping descriptions, resolving CI linting failures (E501).
- Reconstructed and finalized the full `brain/tools.py` file for PR #120, ensuring all new tools (`update_issue`, `post_issue_comment`) and existing tools have correct handlers and are properly registered.
- Preserved the truncation limit increase to 50,000 characters for `read_file` as requested in the original PR.

*The tools are now sharp and the path is clear.*
