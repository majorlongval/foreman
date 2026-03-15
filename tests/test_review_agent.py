import unittest
import logging
import sys
import os

# Ensure the parent directory is in the path so we can import review_agent
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from review_agent import (
        is_source_file,
        is_test_file,
        is_config_only,
        has_test_evidence,
        validate_test_presence,
        LABEL_SKIP_REVIEW
    )
except ImportError:
    # This will be resolved once review_agent.py is updated with the new functions
    pass

# Logging setup to match agent style
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman-test-presence")

class TestReviewAgentPresence(unittest.TestCase):
    """
    Unit tests for automated test-presence checks in review_agent.py.
    This covers source detection, config exclusions, and evidence verification.
    """

    def setUp(self):
        try:
            log.info(f"Setting up test: {self._testMethodName}")
        except Exception as e:
            log.error(f"Setup failure: {e}")

    def test_is_source_file(self):
        """Verify logic for identifying source code changes."""
        try:
            self.assertTrue(is_source_file("agent_loop.py"))
            self.assertTrue(is_source_file("review_agent.py"))
            self.assertTrue(is_source_file("src/commands/init.py"))
            # Test files are NOT source files in this context
            self.assertFalse(is_source_file("tests/test_logic.py"))
            self.assertFalse(is_source_file("test_utils.py"))
            # Config/Docs are NOT source files
            self.assertFalse(is_source_file("README.md"))
            self.assertFalse(is_source_file("requirements.txt"))
            self.assertFalse(is_source_file("pyproject.toml"))
            log.info("test_is_source_file passed")
        except Exception as e:
            log.error(f"Failed test_is_source_file: {e}")
            self.fail(e)

    def test_is_test_file(self):
        """Verify logic for identifying test files."""
        try:
            self.assertTrue(is_test_file("tests/test_agent.py"))
            self.assertTrue(is_test_file("test_core.py"))
            self.assertTrue(is_test_file("tests/integration/test_workflow.py"))
            self.assertFalse(is_test_file("agent.py"))
            self.assertFalse(is_test_file("tests/conftest.py"))
            self.assertFalse(is_test_file("tests/helpers.py"))
            log.info("test_is_test_file passed")
        except Exception as e:
            log.error(f"Failed test_is_test_file: {e}")
            self.fail(e)

    def test_is_config_only(self):
        """Verify exemption for config-only PRs."""
        try:
            self.assertTrue(is_config_only(["requirements.txt", "config.yml", "README.md"]))
            self.assertTrue(is_config_only(["LICENSE", "SECURITY.md", ".gitignore"]))
            self.assertTrue(is_config_only(["pyproject.toml", "poetry.lock"]))
            self.assertFalse(is_config_only(["agent.py", "requirements.txt"]))
            self.assertFalse(is_config_only(["test_agent.py"]))
            log.info("test_is_config_only passed")
        except Exception as e:
            log.error(f"Failed test_is_config_only: {e}")
            self.fail(e)

    def test_has_test_evidence(self):
        """Verify parsing of PR body for pytest execution evidence."""
        try:
            self.assertTrue(has_test_evidence("Changes tested.\n```\npytest\n5 passed\n```"))
            self.assertTrue(has_test_evidence("Logs: PASSED tests/test_agent.py"))
            self.assertTrue(has_test_evidence("I ran `pytest -v` and it passed."))
            self.assertFalse(has_test_evidence("I fixed the typo in the log message."))
            self.assertFalse(has_test_evidence(""))
            self.assertFalse(has_test_evidence(None))
            log.info("test_has_test_evidence passed")
        except Exception as e:
            log.error(f"Failed test_has_test_evidence: {e}")
            self.fail(e)

    def test_validate_test_presence_logic(self):
        """Verify the integrated validation logic returns correct levels."""
        try:
            # Case 1: Exempted by label
            res, msg = validate_test_presence(["src/main.py"], "Bugfix", [LABEL_SKIP_REVIEW])
            self.assertIsNone(res)

            # Case 2: Exempted by file patterns (config/docs only)
            res, msg = validate_test_presence(["README.md", "requirements.txt"], "Update deps", [])
            self.assertIsNone(res)

            # Case 3: Missing tests for source changes (CRITICAL)
            res, msg = validate_test_presence(["agent.py"], "Refactor loop", [])
            self.assertEqual(res, "CRITICAL")
            self.assertIn("Missing corresponding tests", msg)

            # Case 4: Tests present but no evidence (IMPORTANT)
            res, msg = validate_test_presence(["agent.py", "test_agent.py"], "Add feature", [])
            self.assertEqual(res, "IMPORTANT")
            self.assertIn("Missing pytest execution output", msg)

            # Case 5: Tests and evidence present (OK)
            body = "Add feature\n```\npytest tests/test_agent.py\nPASSED\n```"
            res, msg = validate_test_presence(["agent.py", "test_agent.py"], body, [])
            self.assertIsNone(res)

            # Case 6: Only test files modified, no evidence (IMPORTANT)
            res, msg = validate_test_presence(["test_agent.py"], "Fix tests", [])
            self.assertEqual(res, "IMPORTANT")
            self.assertIn("Missing pytest execution output", msg)
            
            log.info("test_validate_test_presence_logic passed")
        except Exception as e:
            log.error(f"Failed test_validate_test_presence_logic: {e}")
            self.fail(e)

if __name__ == "__main__":
    unittest.main()