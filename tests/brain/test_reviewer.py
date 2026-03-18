import pytest
from brain.reviewer.reviewer import Reviewer
from brain.reviewer.static_analysis import StaticAnalyzer, AnalysisIssue

def test_reviewer_initialization():
    reviewer = Reviewer()
    assert isinstance(reviewer.analyzer, StaticAnalyzer)

def test_reviewer_review_pr_empty():
    reviewer = Reviewer()
    pr_data = {"number": 1, "changed_files": []}
    result = reviewer.review_pr(pr_data)
    
    assert result["pr_number"] == 1
    assert result["analysis_issues"] == []
    assert "Reviewed 0 files" in result["summary"]

def test_static_analyzer_run_all():
    analyzer = StaticAnalyzer()
    issues = analyzer.run_all(["file1.py"])
    assert issues == []
