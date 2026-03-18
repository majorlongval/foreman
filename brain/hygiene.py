"""Backlog Hygiene Agent - Core Logic.

Focuses on deduplication and issue hygiene.
"""

import logging
from typing import List, Tuple, Dict

log = logging.getLogger("foreman.brain.hygiene")

class Deduplicator:
    """Identifies potential duplicate issues in the backlog."""

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate a simple Jaccard similarity between two strings."""
        if not text1 or not text2:
            return 0.0
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        return len(intersection) / len(union)

    def find_potential_duplicates(self, issues: List[Dict]) -> List[Tuple[Dict, Dict, float]]:
        """Compare all open issues and find pairs above the similarity threshold."""
        duplicates = []
        for i in range(len(issues)):
            for j in range(i + 1, len(issues)):
                issue1 = issues[i]
                issue2 = issues[j]
                
                # Compare titles
                title_sim = self.calculate_similarity(issue1["title"], issue2["title"])
                
                # Compare bodies
                body_sim = self.calculate_similarity(issue1.get("body", "") or "", issue2.get("body", "") or "")
                
                # Weighted average: titles are often more indicative of duplicates
                combined_sim = (title_sim * 0.7) + (body_sim * 0.3)
                
                if combined_sim >= self.threshold:
                    duplicates.append((issue1, issue2, combined_sim))
        
        return sorted(duplicates, key=lambda x: x[2], reverse=True)

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
    
    return "\n".join(report)

# TODO: Research issue promotion automation
# Potential triggers: 
# - Specific labels (e.g., 'promoted', 'high-priority')
# - Number of reactions
# - Linked PRs or discussions
