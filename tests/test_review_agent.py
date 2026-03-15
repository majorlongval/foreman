import unittest
import logging
from unittest.mock import MagicMock, patch
from review_agent import PRReviewer, LABEL_SKIP_REVIEW

# Setup logging to see output during tests
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("test-review-agent")

class TestReviewAgentTestPresence(unittest.TestCase):
    def setUp(self):
        # Mock dependencies to avoid real API calls and filesystem access
        with patch('review_agent.Github'):
            with patch('review_agent.LLMClient'):
                with patch('review_agent.ModelRouter'):
                    with patch('review_agent.CostTracker'):
                        self.reviewer = PRReviewer("fake-token", "owner/repo")

    def create_mock_pr(self, files, body="", labels=None):
        pr = MagicMock()
        # Mock get_files() to return list of mock File objects
        mock_files = []
        for f in files:
            m = MagicMock()
            m.filename = f
            mock_files.append(m)
        pr.get_files.return_value = mock_files
        pr.body = body
        # Mock labels
        pr.labels = [MagicMock(name=l) for l in (labels or [])]
        return pr

    def test_source_changes_missing_tests(self):
        """PR modifies source files but provides no tests."""
        try:
            pr = self.create_mock_pr(["review_agent.py", "llm_client.py"])
            issues = self.reviewer.validate_test_presence(pr)
            self.assertTrue(any("[CRITICAL]" in i and "Missing corresponding tests" in i for i in issues))
            log.info("test_source_changes_missing_tests: PASSED")
        except Exception as e:
            self.fail(f"test_source_changes_missing_tests failed: {e}")

    def test_test_changes_missing_evidence(self):
        """PR modifies test files but provides no execution evidence in body."""
        try:
            pr = self.create_mock_pr(["tests/test_review_agent.py"], body="Updated tests.")
            issues = self.reviewer.validate_test_presence(pr)
            self.assertTrue(any("[IMPORTANT]" in i and "Missing pytest execution output" in i for i in issues))
            log.info("test_test_changes_missing_evidence: PASSED")
        except Exception as e:
            self.fail(f"test_test_changes_missing_evidence failed: {e}")

    def test_source_and_test_with_evidence(self):
        """PR modifies source and tests, and includes pytest output."""
        try:
            body = "Implemented feature.\n```\n============================= 1 passed in 0.01s =============================\n```"
            pr = self.create_mock_pr(["app.py", "tests/test_app.py"], body=body)
            issues = self.reviewer.validate_test_presence(pr)
            self.assertEqual(len(issues), 0, f"Expected no issues, got: {issues}")
            log.info("test_source_and_test_with_evidence: PASSED")
        except Exception as e:
            self.fail(f"test_source_and_test_with_evidence failed: {e}")

    def test_config_only_changes_exempted(self):
        """PR modifying only config/meta files should be exempted."""
        try:
            files = [".github/workflows/main.yml", "package.json", "README.md", "requirements.txt", "pyproject.toml"]
            pr = self.create_mock_pr(files)
            issues = self.reviewer.validate_test_presence(pr)
            self.assertEqual(len(issues), 0)
            log.info("test_config_only_changes_exempted: PASSED")
        except Exception as e:
            self.fail(f"test_config_only_changes_exempted failed: {e}")

    def test_skip_review_label_exempted(self):
        """PR with skip-review label should be exempted."""
        try:
            pr = self.create_mock_pr(["critical_fix.py"], labels=[LABEL_SKIP_REVIEW])
            issues = self.reviewer.validate_test_presence(pr)
            self.assertEqual(len(issues), 0)
            log.info("test_skip_review_label_exempted: PASSED")
        except Exception as e:
            self.fail(f"test_skip_review_label_exempted failed: {e}")

    def test_mixed_config_and_source_checks_source(self):
        """PR with mixed config and source files should still trigger check."""
        try:
            pr = self.create_mock_pr(["README.md", "new_feature.py"])
            issues = self.reviewer.validate_test_presence(pr)
            self.assertTrue(any("[CRITICAL]" in i for i in issues))
            log.info("test_mixed_config_and_source_checks_source: PASSED")
        except Exception as e:
            self.fail(f"test_mixed_config_and_source_checks_source failed: {e}")

    def test_pytest_evidence_detection_variations(self):
        """Check different formats of pytest output evidence."""
        try:
            valid_bodies = [
                "fixed bug. tests:\n```\n1 passed\n```",
                "tests passed.\n```pytest\n5 passed, 2 warnings\n```",
                "output:\n```\n==== 10 passed ====\n```"
            ]
            for body in valid_bodies:
                pr = self.create_mock_pr(["test_logic.py"], body=body)
                issues = self.reviewer.validate_test_presence(pr)
                # Should have no [IMPORTANT] issues regarding evidence
                self.assertFalse(any("[IMPORTANT]" in i and "execution output" in i for i in issues), f"Failed for body: {body}")
            log.info("test_pytest_evidence_detection_variations: PASSED")
        except Exception as e:
            self.fail(f"test_pytest_evidence_detection_variations failed: {e}")

if __name__ == "__main__":
    unittest.main()