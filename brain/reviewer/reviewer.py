"""Core logic for the Reviewer module."""

from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional
from brain.reviewer.static_analysis import StaticAnalyzer, AnalysisIssue

log = logging.getLogger("foreman.brain.reviewer")

class Reviewer:
    """Orchestrates the review process for pull requests."""

    def __init__(self, analyzer: Optional[StaticAnalyzer] = None):
        self.analyzer = analyzer or StaticAnalyzer()

    def review_pr(self, pr_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform a review of a pull request.
        
        This currently serves as the technical foundation for future
        automated reviews including static analysis and LLM-based feedback.
        """
        pr_number = pr_data.get("number")
        log.info(f"Reviewing PR #{pr_number}")
        
        # 1. Get changed files
        changed_files = pr_data.get("changed_files", [])
        
        # 2. Run static analysis
        analysis_issues = self.analyzer.run_all(changed_files)
        
        # 3. Compile results
        return {
            "pr_number": pr_number,
            "analysis_issues": [
                {
                    "file": issue.file,
                    "line": issue.line,
                    "message": issue.message,
                    "tool": issue.tool,
                    "severity": issue.severity,
                }
                for issue in analysis_issues
            ],
            "summary": f"Reviewed {len(changed_files)} files. Found {len(analysis_issues)} issues.",
        }
