from brain.hygiene import Deduplicator

def test_deduplicator_similarity():
    dedup = Deduplicator()
    assert dedup.calculate_similarity("Fix the bug", "Fix the bug") == 1.0
    assert dedup.calculate_similarity("Fix the bug", "Completely different") < 0.2
    assert dedup.calculate_similarity("", "Something") == 0.0

def test_find_potential_duplicates():
    issues = [
        {"number": 1, "title": "Implement issue management", "body": "Need to manage issues."},
        {"number": 2, "title": "Implement issue management tool", "body": "We need a tool for issues."},
        {"number": 3, "title": "Refactor the brain", "body": "The brain is messy."},
    ]
    # Lower threshold to catch the partial match
    dedup = Deduplicator(threshold=0.4)
    duplicates = dedup.find_potential_duplicates(issues)
    
    assert len(duplicates) >= 1
    # Check if the correct issues are identified as duplicates
    # Issue 1 and 2 are very similar
    found_1_2 = False
    for i1, i2, score in duplicates:
        if {i1["number"], i2["number"]} == {1, 2}:
            found_1_2 = True
            break
    assert found_1_2
