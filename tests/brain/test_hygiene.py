"""Tests for the Backlog Hygiene deduplication logic."""

from typing import Any, Dict, List
from brain.hygiene import Deduplicator


def test_deduplicator_similarity() -> None:
    """Test the Jaccard similarity calculation with normalization."""
    dedup = Deduplicator()
    assert dedup.calculate_similarity("Fix the bug", "Fix the bug") == 1.0
    # Test normalization: punctuation and case
    assert dedup.calculate_similarity("Fix the bug!", "fix the bug") == 1.0
    assert dedup.calculate_similarity("Fix the bug", "Completely different") < 0.2
    assert dedup.calculate_similarity("", "Something") == 0.0


def test_find_potential_duplicates() -> None:
    """Test the detection of potential duplicate issues."""
    issues: List[Dict[str, Any]] = [
        {
            "number": 1,
            "title": "Implement issue management",
            "body": "Need to manage issues.",
        },
        {
            "number": 2,
            "title": "Implement issue management tool",
            "body": "We need a tool for issues.",
        },
        {
            "number": 3,
            "title": "Refactor the brain",
            "body": "The brain is messy.",
        },
    ]
    # Lower threshold to catch the partial match
    dedup = Deduplicator(threshold=0.4)
    duplicates = dedup.find_potential_duplicates(issues)

    assert len(duplicates) >= 1
    # Check if the correct issues are identified as duplicates
    # Issue 1 and 2 are very similar
    found_1_2 = False
    for i1, i2, _ in duplicates:
        if {i1["number"], i2["number"]} == {1, 2}:
            found_1_2 = True
            break
    assert found_1_2


def test_deduplicator_missing_body() -> None:
    """Ensure missing or empty bodies are handled robustly."""
    issues: List[Dict[str, Any]] = [
        {"number": 1, "title": "Test Issue", "body": None},
        {"number": 2, "title": "Test Issue", "body": ""},
    ]
    dedup = Deduplicator(threshold=0.5)
    duplicates = dedup.find_potential_duplicates(issues)
    assert len(duplicates) == 1
    # title_sim = 1.0, body_sim = 0.0 (both empty)
    # score = 1.0 * 0.7 + 0.0 * 0.3 = 0.7
    assert round(duplicates[0][2], 2) == 0.7


def test_configurable_weights() -> None:
    """Test that changing weights affects the similarity score."""
    issues: List[Dict[str, Any]] = [
        {"number": 1, "title": "A", "body": "B"},
        {"number": 2, "title": "A", "body": "C"},
    ]
    # title_sim = 1.0, body_sim = 0.0
    # Default (0.7, 0.3) -> 0.7
    dedup1 = Deduplicator(threshold=0.1)
    duplicates1 = dedup1.find_potential_duplicates(issues)
    assert round(duplicates1[0][2], 2) == 0.70

    # Custom (0.5, 0.5) -> 0.5
    dedup2 = Deduplicator(threshold=0.1, title_weight=0.5, body_weight=0.5)
    duplicates2 = dedup2.find_potential_duplicates(issues)
    assert round(duplicates2[0][2], 2) == 0.50


def test_default_threshold() -> None:
    """Verify that similar issues pass the default threshold."""
    dedup = Deduplicator()
    # Very similar titles
    issues: List[Dict[str, Any]] = [
        {
            "number": 1,
            "title": "Fix the logic bug in core",
            "body": "Small bug in core logic.",
        },
        {
            "number": 2,
            "title": "Fix logic bug in core",
            "body": "There is a logic bug in the core module.",
        },
    ]
    duplicates = dedup.find_potential_duplicates(issues)
    # title_sim = 5/6 = 0.833
    # body_sim = 4/10 = 0.4
    # score = 0.5831 + 0.12 = 0.7031
    assert len(duplicates) == 1
