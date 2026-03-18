"""Tests for brain.survey — gather world state for council deliberation."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from brain.config import AgentConfig, Config
from brain.survey import SurveyResult, _read_recent_files, gather_survey


def make_config(daily_limit: float = 5.0) -> Config:
    return Config(
        daily_limit_usd=daily_limit,
        model_default="gemini/gemini-2.5-flash",
        model_reasoning="gemini/gemini-2.5-pro",
        model_council="anthropic/claude-sonnet-4-6",
        model_elrond="gemini/gemini-3-pro-preview",
        agents=[
            AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
        ],
        council_enabled=True,
        max_cycles_per_day=12,
        telegram_enabled=True,
    )


class TestSurveyResult(unittest.TestCase):
    def test_budget_remaining(self) -> None:
        result = SurveyResult(
            budget_limit=5.0, budget_spent=1.50,
            open_issues=[], open_prs=[],
            recent_incidents=[], shared_decisions=[],
            journal_last_entry=None,
        )
        self.assertEqual(result.budget_remaining, 3.50)

    def test_budget_exhausted(self) -> None:
        result = SurveyResult(
            budget_limit=5.0, budget_spent=5.50,
            open_issues=[], open_prs=[],
            recent_incidents=[], shared_decisions=[],
            journal_last_entry=None,
        )
        self.assertTrue(result.budget_exhausted)

    def test_to_context_string_includes_budget(self) -> None:
        result = SurveyResult(
            budget_limit=5.0, budget_spent=2.0,
            open_issues=["#95: Auto-promote"],
            open_prs=["PR #99: Fix thing"],
            recent_incidents=[],
            shared_decisions=["Use flash for reviews"],
            journal_last_entry="Cycle 3: reviewed PR #99",
        )
        ctx = result.to_context_string()
        self.assertIn("$3.00 remaining", ctx)
        self.assertIn("#95", ctx)
        self.assertIn("PR #99", ctx)


class TestReadRecentFiles(unittest.TestCase):
    def test_returns_most_recent_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "a.md").write_text("oldest")
            (tmp_path / "c.md").write_text("newest")
            (tmp_path / "b.md").write_text("middle")
            results = _read_recent_files(tmp_path, limit=2)
            self.assertEqual(results, ["newest", "middle"])

    def test_respects_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            for i in range(10):
                (tmp_path / f"{i:02d}.md").write_text(f"entry {i}")
            results = _read_recent_files(tmp_path, limit=3)
            self.assertEqual(len(results), 3)

    def test_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            results = _read_recent_files(tmp_path)
            self.assertEqual(results, [])

    def test_nonexistent_directory(self) -> None:
        results = _read_recent_files(Path("/nonexistent"))
        self.assertEqual(results, [])


class TestInbox(unittest.TestCase):
    def test_inbox_included_in_context_string(self) -> None:
        """When inbox_note is set, to_context_string includes a Notes from Jord section."""
        result = SurveyResult(
            budget_limit=5.0, budget_spent=0.0,
            open_issues=[], open_prs=[],
            recent_incidents=[], shared_decisions=[],
            journal_last_entry=None,
            inbox_note="Please diversify your perspectives.",
        )
        ctx = result.to_context_string()
        self.assertIn("Notes from Jord", ctx)
        self.assertIn("Please diversify your perspectives.", ctx)

    def test_inbox_absent_no_notes_section(self) -> None:
        """When inbox_note is None, to_context_string has no Notes from Jord section."""
        result = SurveyResult(
            budget_limit=5.0, budget_spent=0.0,
            open_issues=[], open_prs=[],
            recent_incidents=[], shared_decisions=[],
            journal_last_entry=None,
        )
        ctx = result.to_context_string()
        self.assertNotIn("Notes from Jord", ctx)

    def test_gather_survey_reads_inbox(self) -> None:
        """gather_survey reads INBOX.md from repo_root and sets inbox_note."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            repo_root = tmp_path / "repo"
            repo_root.mkdir()
            memory_root = tmp_path / "memory"
            for d in ["costs", "decisions", "journal", "incidents"]:
                (memory_root / "shared" / d).mkdir(parents=True)
            (repo_root / "INBOX.md").write_text("Hello agents.")
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = []
            mock_repo.get_pulls.return_value = []
            result = gather_survey(make_config(), memory_root, mock_repo, repo_root=repo_root)
            self.assertEqual(result.inbox_note, "Hello agents.")

    def test_gather_survey_empty_inbox_returns_none(self) -> None:
        """gather_survey returns inbox_note=None when INBOX.md is empty or absent."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            repo_root = tmp_path / "repo"
            repo_root.mkdir()
            memory_root = tmp_path / "memory"
            for d in ["costs", "decisions", "journal", "incidents"]:
                (memory_root / "shared" / d).mkdir(parents=True)
            (repo_root / "INBOX.md").write_text("   ")  # whitespace only
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = []
            mock_repo.get_pulls.return_value = []
            result = gather_survey(make_config(), memory_root, mock_repo, repo_root=repo_root)
            self.assertIsNone(result.inbox_note)


class TestPrCommentsSurvey(unittest.TestCase):
    def _make_memory(self, tmp_path: Path) -> Path:
        memory_root = tmp_path / "memory"
        for d in ["costs", "decisions", "journal", "incidents"]:
            (memory_root / "shared" / d).mkdir(parents=True)
        return memory_root

    def test_pr_comments_included_in_context_string(self) -> None:
        """When a PR has comments, to_context_string shows them under the PR."""
        result = SurveyResult(
            budget_limit=5.0, budget_spent=0.0,
            open_issues=[], open_prs=[],
            recent_incidents=[], shared_decisions=[],
            journal_last_entry=None,
            pr_comments={"PR #42: Add executor": ["galadriel: Missing tests."]},
        )
        ctx = result.to_context_string()
        assert "Missing tests." in ctx

    def test_pr_comments_absent_when_empty(self) -> None:
        """When no PR comments, to_context_string has no comments section."""
        result = SurveyResult(
            budget_limit=5.0, budget_spent=0.0,
            open_issues=[], open_prs=[],
            recent_incidents=[], shared_decisions=[],
            journal_last_entry=None,
        )
        ctx = result.to_context_string()
        assert "PR Comments" not in ctx

    def test_gather_survey_fetches_pr_comments(self) -> None:
        """gather_survey fetches comments from open PRs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            memory_root = self._make_memory(tmp_path)
            mock_comment = MagicMock()
            mock_comment.user.login = "galadriel-bot"
            mock_comment.body = "Needs more tests."
            mock_pr = MagicMock()
            mock_pr.number = 42
            mock_pr.title = "Add executor"
            mock_pr.get_issue_comments.return_value = [mock_comment]
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = []
            mock_repo.get_pulls.return_value = [mock_pr]
            result = gather_survey(make_config(), memory_root, mock_repo)
            assert any("Needs more tests." in c for comments in result.pr_comments.values() for c in comments)

    def test_gather_survey_pr_comments_empty_when_no_prs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            memory_root = self._make_memory(tmp_path)
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = []
            mock_repo.get_pulls.return_value = []
            result = gather_survey(make_config(), memory_root, mock_repo)
            assert result.pr_comments == {}


class TestGatherSurvey(unittest.TestCase):
    def test_gathers_budget_from_cost_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            memory_root = tmp_path / "memory"
            costs_dir = memory_root / "shared" / "costs"
            costs_dir.mkdir(parents=True)
            (memory_root / "shared" / "decisions").mkdir()
            (memory_root / "shared" / "journal").mkdir()
            (memory_root / "shared" / "incidents").mkdir()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            (costs_dir / f"{today}.jsonl").write_text(json.dumps({"cost_usd": 1.50}) + "\n")
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = []
            mock_repo.get_pulls.return_value = []
            result = gather_survey(make_config(), memory_root, mock_repo)
            self.assertAlmostEqual(result.budget_spent, 1.50, places=3)
            self.assertAlmostEqual(result.budget_remaining, 3.50, places=3)

    def test_gathers_open_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            memory_root = tmp_path / "memory"
            for d in ["costs", "decisions", "journal", "incidents"]:
                (memory_root / "shared" / d).mkdir(parents=True)
            mock_issue = MagicMock()
            mock_issue.number = 95
            mock_issue.title = "Auto-promote"
            mock_issue.labels = []
            mock_issue.pull_request = None
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = [mock_issue]
            mock_repo.get_pulls.return_value = []
            result = gather_survey(make_config(), memory_root, mock_repo)
            self.assertEqual(len(result.open_issues), 1)
            self.assertIn("#95", result.open_issues[0])

    def test_reads_recent_incidents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            memory_root = tmp_path / "memory"
            for d in ["costs", "decisions", "journal", "incidents"]:
                (memory_root / "shared" / d).mkdir(parents=True)
            (memory_root / "shared" / "incidents" / "error.md").write_text("LLM failed")
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = []
            mock_repo.get_pulls.return_value = []
            result = gather_survey(make_config(), memory_root, mock_repo)
            self.assertEqual(len(result.recent_incidents), 1)
            self.assertIn("LLM failed", result.recent_incidents[0])


if __name__ == "__main__":
    unittest.main()
