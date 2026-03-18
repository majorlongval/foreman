"""Backlog Hygiene Agent - Core Logic.

Focuses on deduplication and issue hygiene.
"""

import logging
import re
from typing import Dict, List, Tuple

log = logging.getLogger("foreman.brain.hygiene")


class Deduplicator:
    """Identifies potential duplicate issues in the backlog."""

    def __init__(
        self,
        threshold: float = 0.7,
        title_weight: float = 0.7,
        body_weight: float = 0.3,
    ):
        """Initialize the Deduplicator.

        Args:
            threshold: The similarity score above which issues are considered duplicates.
            title_weight: The weight given to title similarity (0.0 to 1.0).
            body_weight: The weight given to body similarity (0.0 to 1.0).
        """
        self.threshold = threshold
        self.title_weight = title_weight
        self.body_weight = body_weight

    def _normalize(self, text: str) -> str:
        """Normalize a string for comparison.

        Converts to lowercase and removes punctuation/special characters.
        """
        text = text.lower()
        # Remove punctuation and special characters
        text = re.sub(r"[^a-z0-9\s]", "", text)
        return text

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate a simple Jaccard similarity between two strings."""
        if not text1 or not text2:
            return 0.0

        norm1 = self._normalize(text1)
        norm2 = self._normalize(text2)

        words1 = set(norm1.split())
        words2 = set(norm2.split())

        if not words1 or not words2:
            return 0.0

        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union)

    def find_potential_duplicates(
        self, issues: List[Dict]
    ) -> List[Tuple[Dict, Dict, float]]:
        """Compare all open issues and find pairs above the similarity threshold."""
        duplicates = []
        for i in range(len(issues)):
            for j in range(i + 1, len(issues)):
                issue1 = issues[i]
                issue2 = issues[j]

                combined_sim = self._get_combined_similarity(issue1, issue2)

                if combined_sim >= self.threshold:
                    duplicates.append((issue1, issue2, combined_sim))

        return sorted(duplicates, key=lambda x: x[2], reverse=True)

    def _get_combined_similarity(self, issue1: Dict, issue2: Dict) -> float:
        """Calculate weighted similarity between two issues."""
        title_sim = self.calculate_similarity(issue1["title"], issue2["title"])

        body1 = issue1.get("body", "") or ""
        body2 = issue2.get("body", "") or ""
        body_sim = self.calculate_similarity(body1, body2)

        return (title_sim * self.title_weight) + (body_sim * self.body_weight)


def format_duplication_report(duplicates: List[Tuple[Dict, Dict, float]]) -> str:
    """Format the list of potential duplicates into a readable report."""
    if not duplicates:
        return "No potential duplicates found."

    report = ["### Potential Duplicate Issues Report", ""]
    for issue1, issue2, score in duplicates:
        report.append(f"- **{score:.2%} Match**")
        report.append(f"  - #{issue1['number']}: {issue1['title']}")
        report.append(f"  - #{issue2['number']}: {issue2['title']}")
        report.append("")

    return "\n".join(report).strip()


# TODO: Research issue promotion automation
# Potential triggers:
# - Specific labels (e.g., 'promoted', 'high-priority')
# - Number of reactions
# - Linked PRs or discussions
