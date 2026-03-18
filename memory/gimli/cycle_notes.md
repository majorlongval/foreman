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
