import unittest
from unittest.mock import MagicMock, patch
import logging
import sys
import os

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test-review-agent")

class TestReviewAgentTestPresence(unittest.TestCase):
    """
    Unit tests for automated test-presence checks in the Review Agent.
    Covers: missing tests, missing PR body evidence, and exclusions.
    """

    def setUp(self):
        """
        Initialize PRReviewer with mocked dependencies.
        """
        try:
            with patch('review_agent.Github'), \
                 patch('review_agent.LLMClient'), \
                 patch('review_agent.ModelRouter'), \
                 patch('review_agent.CostTracker'):
                from review_agent import PRReviewer
                self.reviewer = PRReviewer("fake-token", "owner/repo", dry_run=True)
        except Exception as e:
            log.error(f"Failed to set up TestReviewAgentTestPresence: {e}")
            raise

    def test_validate_test_presence_config_only(self):
        """
        PRs modifying only configuration or documentation should be exempt from test checks.
        """
        try:
            log.info("Starting test_validate_test_presence_config_only")
            pr = MagicMock()
            pr.labels = []
            pr.body = "Updated the project configuration and documentation."
            
            # List of files that should trigger exemption
            files = [
                "README.md", 
                "requirements.txt", 
                "package.json", 
                "config.toml", 
                "deploy.yml",
                "settings.json"
            ]
            
            result = self.reviewer._validate_test_presence(pr, files)
            self.assertIsNone(result, "PR with only config/docs should not be flagged.")
            log.info("✅ test_validate_test_presence_config_only passed")
        except Exception as e:
            log.error(f"test_validate_test_presence_config_only failed: {e}")
            raise
    def test_validate_test_presence_missing_tests(self):
        """
        PRs modifying source files (.py) without adding/modifying test files should be flagged CRITICAL.
        """
        try:
            log.info("Starting test_validate_test_presence_missing_tests")
            pr = MagicMock()
            pr.labels = []
            pr.body = "Refactored core logic to improve performance."
            
            # Modifying source code but no test files
            files = ["core/engine.py", "utils/helper.py"]
            
            result = self.reviewer._validate_test_presence(pr, files)
            self.assertIsNotNone(result, "PR modifying source without tests should be flagged.")
            self.assertIn("[CRITICAL]", result)
            self.assertIn("missing tests", result.lower())
            log.info("✅ test_validate_test_presence_missing_tests passed")
        except Exception as e:
            log.error(f"test_validate_test_presence_missing_tests failed: {e}")
            raise
    def test_validate_test_presence_missing_evidence(self):
        """
        PRs including tests but lacking execution output in the description should be flagged IMPORTANT.
        """
        try:
            log.info("Starting test_validate_test_presence_missing_evidence")
            pr = MagicMock()
            pr.labels = []
            pr.body = "Added new feature and unit tests. Ready for review."
            
            # Source and test file both present
            files = ["feature.py", "tests/test_feature.py"]
            
            result = self.reviewer._validate_test_presence(pr, files)
            self.assertIsNotNone(result, "PR with tests but no execution evidence should be flagged.")
            self.assertIn("[IMPORTANT]", result)
            self.assertIn("pytest execution output", result.lower())
            log.info("✅ test_validate_test_presence_missing_evidence passed")
        except Exception as e:
            log.error(f"test_validate_test_presence_missing_evidence failed: {e}")
            raise
    def test_validate_test_presence_valid(self):
        """
        PRs with tests and pytest execution output in the body should pass.
        """
        try:
            log.info("Starting test_validate_test_presence_valid")
            pr = MagicMock()
            pr.labels = []
            pr.body = """
            Implemented feature X.
            
            Test execution:
            ```
            ======= 12 passed, 2 skipped in 4.56s =======
            ```
            """
            
            # Supports both tests/test_*.py and test_*.py
            files = ["logic.py", "test_logic.py"]
            
            result = self.reviewer._validate_test_presence(pr, files)
            self.assertIsNone(result, "Valid PR with tests and evidence should not be flagged.")
            log.info("✅ test_validate_test_presence_valid passed")
        except Exception as e:
            log.error(f"test_validate_test_presence_valid failed: {e}")
            raise
    def test_validate_test_presence_skip_review(self):
        """
        PRs with the skip-review label should be exempt from test-presence checks.
        """
        try:
            log.info("Starting test_validate_test_presence_skip_review")
            from review_agent import LABEL_SKIP_REVIEW
            
            pr = MagicMock()
            label = MagicMock()
            label.name = LABEL_SKIP_REVIEW
            pr.labels = [label]
            pr.body = "Urgent fix for production outage."
            
            # Even though source is modified without tests, skip-review label should override
            files = ["agent_loop.py"]
            
            result = self.reviewer._validate_test_presence(pr, files)
            self.assertIsNone(result, "PRs with skip-review label should be exempted from checks.")
            log.info("✅ test_validate_test_presence_skip_review passed")
        except Exception as e:
            log.error(f"test_validate_test_presence_skip_review failed: {e}")
            raise

if __name__ == "__main__":
    try:
        unittest.main()
    except Exception as e:
        log.error(f"Test runner crashed: {e}")
        sys.exit(1)