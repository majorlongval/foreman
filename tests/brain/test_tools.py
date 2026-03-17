"""Tests for brain.tools — seed toolset definitions and execution."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path
from brain.tools import TOOL_SCHEMAS, execute_tool, ToolContext


@pytest.fixture
def tool_context(tmp_path: Path) -> ToolContext:
    memory_root = tmp_path / "memory"
    (memory_root / "shared" / "costs").mkdir(parents=True)
    (memory_root / "shared" / "decisions").mkdir(parents=True)
    (memory_root / "gandalf").mkdir(parents=True)
    return ToolContext(
        repo=MagicMock(),
        memory_root=memory_root,
        agent_name="gandalf",
        notify_fn=MagicMock(return_value=True),
        costs_dir=memory_root / "shared" / "costs",
    )


class TestToolSchemas:
    def test_all_schemas_have_name(self) -> None:
        for schema in TOOL_SCHEMAS:
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema

    def test_expected_tools_present(self) -> None:
        names = {s["name"] for s in TOOL_SCHEMAS}
        expected = {
            "read_file", "create_issue", "create_pr",
            "read_memory", "write_memory", "send_telegram",
            "check_budget", "list_issues", "list_prs",
        }
        assert expected.issubset(names)


class TestReadMemoryTool:
    def test_read_own_memory(self, tool_context: ToolContext) -> None:
        (tool_context.memory_root / "gandalf" / "notes.md").write_text("My notes")
        result = execute_tool("read_memory", {"path": "gandalf/notes.md"}, tool_context)
        assert "My notes" in result

    def test_read_shared_memory(self, tool_context: ToolContext) -> None:
        (tool_context.memory_root / "shared" / "decisions" / "d.md").write_text("Decision X")
        result = execute_tool("read_memory", {"path": "shared/decisions/d.md"}, tool_context)
        assert "Decision X" in result

    def test_read_other_agent_blocked(self, tool_context: ToolContext) -> None:
        result = execute_tool("read_memory", {"path": "gimli/notes.md"}, tool_context)
        assert "permission" in result.lower() or "cannot" in result.lower()


class TestWriteMemoryTool:
    def test_write_own_memory(self, tool_context: ToolContext) -> None:
        result = execute_tool(
            "write_memory",
            {"path": "gandalf/log.md", "content": "Today I explored."},
            tool_context,
        )
        assert "wrote" in result.lower() or "written" in result.lower()
        assert (tool_context.memory_root / "gandalf" / "log.md").read_text() == "Today I explored."

    def test_write_shared_memory(self, tool_context: ToolContext) -> None:
        execute_tool(
            "write_memory",
            {"path": "shared/decisions/new.md", "content": "We decided Y."},
            tool_context,
        )
        assert (tool_context.memory_root / "shared" / "decisions" / "new.md").read_text() == "We decided Y."


class TestCheckBudgetTool:
    def test_returns_budget_info(self, tool_context: ToolContext) -> None:
        result = execute_tool("check_budget", {}, tool_context)
        assert "$" in result


class TestSendTelegramTool:
    def test_calls_notify(self, tool_context: ToolContext) -> None:
        result = execute_tool(
            "send_telegram",
            {"message": "Hello Jord!"},
            tool_context,
        )
        tool_context.notify_fn.assert_called_once_with("Hello Jord!")


class TestApprovePrTool:
    def test_critic_can_approve_pr(self, tmp_path: Path) -> None:
        """An agent with role 'critic' should be able to approve a PR."""
        memory_root = tmp_path / "memory"
        (memory_root / "shared" / "costs").mkdir(parents=True)
        (memory_root / "galadriel").mkdir(parents=True)
        mock_pr = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        ctx = ToolContext(
            repo=mock_repo,
            memory_root=memory_root,
            agent_name="galadriel",
            agent_role="critic",
            notify_fn=MagicMock(),
            costs_dir=memory_root / "shared" / "costs",
        )
        result = execute_tool("approve_pr", {"pr_number": 102, "comment": "LGTM"}, ctx)
        mock_pr.create_review.assert_called_once_with(body="LGTM", event="APPROVE")
        assert "approved" in result.lower()

    def test_non_critic_cannot_approve_pr(self, tool_context: ToolContext) -> None:
        """Only the critic role can approve PRs."""
        ctx = ToolContext(
            repo=tool_context.repo,
            memory_root=tool_context.memory_root,
            agent_name="gimli",
            agent_role="builder",
            notify_fn=tool_context.notify_fn,
            costs_dir=tool_context.costs_dir,
        )
        result = execute_tool("approve_pr", {"pr_number": 102, "comment": "looks good"}, ctx)
        ctx.repo.get_pull.assert_not_called()
        assert "only" in result.lower() or "critic" in result.lower()


class TestReadPrTool:
    def test_returns_title_and_body(self, tool_context: ToolContext) -> None:
        mock_pr = MagicMock()
        mock_pr.title = "Add executor"
        mock_pr.body = "Wires up the tool loop."
        mock_pr.number = 42
        mock_pr.get_files.return_value = []
        mock_pr.get_issue_comments.return_value = []
        tool_context.repo.get_pull.return_value = mock_pr
        result = execute_tool("read_pr", {"pr_number": 42}, tool_context)
        assert "Add executor" in result
        assert "Wires up the tool loop." in result

    def test_returns_changed_files(self, tool_context: ToolContext) -> None:
        mock_file = MagicMock()
        mock_file.filename = "brain/executor.py"
        mock_file.patch = "@@@ +1 def foo(): pass"
        mock_pr = MagicMock()
        mock_pr.title = "T"
        mock_pr.body = "B"
        mock_pr.number = 42
        mock_pr.get_files.return_value = [mock_file]
        mock_pr.get_issue_comments.return_value = []
        tool_context.repo.get_pull.return_value = mock_pr
        result = execute_tool("read_pr", {"pr_number": 42}, tool_context)
        assert "brain/executor.py" in result

    def test_truncates_long_diff(self, tool_context: ToolContext) -> None:
        mock_file = MagicMock()
        mock_file.filename = "big.py"
        mock_file.patch = "x" * 20000
        mock_pr = MagicMock()
        mock_pr.title = "T"
        mock_pr.body = "B"
        mock_pr.number = 42
        mock_pr.get_files.return_value = [mock_file]
        mock_pr.get_issue_comments.return_value = []
        tool_context.repo.get_pull.return_value = mock_pr
        result = execute_tool("read_pr", {"pr_number": 42}, tool_context)
        assert "truncated" in result
        assert len(result) < 20000

    def test_returns_existing_comments(self, tool_context: ToolContext) -> None:
        mock_comment = MagicMock()
        mock_comment.user.login = "galadriel-bot"
        mock_comment.body = "Missing tests."
        mock_pr = MagicMock()
        mock_pr.title = "T"
        mock_pr.body = "B"
        mock_pr.number = 42
        mock_pr.get_files.return_value = []
        mock_pr.get_issue_comments.return_value = [mock_comment]
        tool_context.repo.get_pull.return_value = mock_pr
        result = execute_tool("read_pr", {"pr_number": 42}, tool_context)
        assert "Missing tests." in result

    def test_handles_nonexistent_pr(self, tool_context: ToolContext) -> None:
        tool_context.repo.get_pull.side_effect = Exception("Not found")
        result = execute_tool("read_pr", {"pr_number": 999}, tool_context)
        assert "error" in result.lower()


class TestPostCommentTool:
    def test_posts_comment_on_pr(self, tool_context: ToolContext) -> None:
        mock_pr = MagicMock()
        tool_context.repo.get_pull.return_value = mock_pr
        result = execute_tool(
            "post_comment", {"pr_number": 42, "body": "LGTM, but add tests."}, tool_context
        )
        mock_pr.create_issue_comment.assert_called_once_with("LGTM, but add tests.")
        assert "comment" in result.lower()

    def test_handles_api_error(self, tool_context: ToolContext) -> None:
        tool_context.repo.get_pull.side_effect = Exception("API error")
        result = execute_tool(
            "post_comment", {"pr_number": 42, "body": "looks good"}, tool_context
        )
        assert "error" in result.lower()
