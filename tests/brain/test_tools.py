"""Tests for brain.tools — seed toolset definitions and execution."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path
from github import GithubException
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
        execute_tool(
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

    def test_includes_passing_ci_checks(self, tool_context: ToolContext) -> None:
        """read_pr must show CI check results so Galadriel can block on failures."""
        check = MagicMock()
        check.name = "lint"
        check.conclusion = "success"
        commit = MagicMock()
        commit.get_check_runs.return_value = [check]
        tool_context.repo.get_commit.return_value = commit

        mock_pr = MagicMock()
        mock_pr.title = "T"
        mock_pr.body = "B"
        mock_pr.number = 42
        mock_pr.head.sha = "abc123"
        mock_pr.get_files.return_value = []
        mock_pr.get_issue_comments.return_value = []
        tool_context.repo.get_pull.return_value = mock_pr

        result = execute_tool("read_pr", {"pr_number": 42}, tool_context)
        assert "lint" in result
        assert "success" in result

    def test_includes_failing_ci_checks(self, tool_context: ToolContext) -> None:
        """A failing check must be clearly visible so Galadriel refuses to approve."""
        check = MagicMock()
        check.name = "lint"
        check.conclusion = "failure"
        commit = MagicMock()
        commit.get_check_runs.return_value = [check]
        tool_context.repo.get_commit.return_value = commit

        mock_pr = MagicMock()
        mock_pr.title = "T"
        mock_pr.body = "B"
        mock_pr.number = 42
        mock_pr.head.sha = "abc123"
        mock_pr.get_files.return_value = []
        mock_pr.get_issue_comments.return_value = []
        tool_context.repo.get_pull.return_value = mock_pr

        result = execute_tool("read_pr", {"pr_number": 42}, tool_context)
        assert "lint" in result
        assert "failure" in result

    def test_ci_checks_fetch_failure_does_not_break_read_pr(self, tool_context: ToolContext) -> None:
        """If the checks API fails, read_pr should still return the rest of the PR."""
        tool_context.repo.get_commit.side_effect = Exception("API error")

        mock_pr = MagicMock()
        mock_pr.title = "My PR"
        mock_pr.body = "B"
        mock_pr.number = 42
        mock_pr.head.sha = "abc123"
        mock_pr.get_files.return_value = []
        mock_pr.get_issue_comments.return_value = []
        tool_context.repo.get_pull.return_value = mock_pr

        result = execute_tool("read_pr", {"pr_number": 42}, tool_context)
        assert "My PR" in result  # still returns PR content
        assert "error" not in result.lower()  # does not surface the checks error


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


class TestCreatePrUpdatesExistingFiles:
    """create_pr should update files that already exist rather than creating them.

    GitHub's Contents API raises a 422 if you call create_file on a path that
    already has content. We detect existing files via get_contents and route to
    update_file so agents can modify PHILOSOPHY.md, agent identity files, etc.
    """

    def _make_ctx(self, tmp_path: Path) -> ToolContext:
        memory_root = tmp_path / "memory"
        (memory_root / "shared" / "costs").mkdir(parents=True)
        (memory_root / "gandalf").mkdir(parents=True)
        return ToolContext(
            repo=MagicMock(),
            memory_root=memory_root,
            agent_name="gandalf",
            notify_fn=MagicMock(return_value=True),
            costs_dir=memory_root / "shared" / "costs",
        )

    def test_updates_existing_file_instead_of_creating(self, tmp_path: Path) -> None:
        """When get_contents returns a file object, update_file must be called."""
        ctx = self._make_ctx(tmp_path)
        existing_file = MagicMock()
        existing_file.sha = "abc123"
        ctx.repo.get_contents.return_value = existing_file
        mock_pr = MagicMock()
        mock_pr.number = 10
        mock_pr.title = "Update philosophy"
        ctx.repo.create_pull.return_value = mock_pr
        main_ref = MagicMock()
        main_ref.object.sha = "deadbeef"
        ctx.repo.get_git_ref.return_value = main_ref

        result = execute_tool(
            "create_pr",
            {
                "branch": "patch/update-philosophy",
                "title": "Update philosophy",
                "body": "Adds self-modification section.",
                "files": [{"path": "PHILOSOPHY.md", "content": "new content"}],
            },
            ctx,
        )

        ctx.repo.update_file.assert_called_once_with(
            path="PHILOSOPHY.md",
            message="Update PHILOSOPHY.md",
            content="new content",
            sha="abc123",
            branch="patch/update-philosophy",
        )
        ctx.repo.create_file.assert_not_called()
        assert "PR #10" in result

    def test_creates_new_file_when_not_existing(self, tmp_path: Path) -> None:
        """When get_contents raises GithubException (404), create_file must be called."""
        ctx = self._make_ctx(tmp_path)
        # Simulate file not found — PyGithub raises GithubException with status 404
        ctx.repo.get_contents.side_effect = GithubException(404, "Not Found", None)
        mock_pr = MagicMock()
        mock_pr.number = 11
        mock_pr.title = "Add new file"
        ctx.repo.create_pull.return_value = mock_pr
        main_ref = MagicMock()
        main_ref.object.sha = "deadbeef"
        ctx.repo.get_git_ref.return_value = main_ref

        result = execute_tool(
            "create_pr",
            {
                "branch": "patch/new-file",
                "title": "Add new file",
                "body": "Adds a brand new file.",
                "files": [{"path": "agents/new_agent.md", "content": "hello"}],
            },
            ctx,
        )

        ctx.repo.create_file.assert_called_once_with(
            path="agents/new_agent.md",
            message="Add agents/new_agent.md",
            content="hello",
            branch="patch/new-file",
        )
        ctx.repo.update_file.assert_not_called()
        assert "PR #11" in result


class TestListFilesTool:
    """list_files wraps repo.get_contents to let agents explore the repo."""

    def test_lists_root_files(self, tool_context: ToolContext) -> None:
        """Default (empty path) lists the repo root."""
        f1 = MagicMock()
        f1.name = "README.md"
        f1.type = "file"
        d1 = MagicMock()
        d1.name = "brain"
        d1.type = "dir"
        tool_context.repo.get_contents.return_value = [f1, d1]

        result = execute_tool("list_files", {}, tool_context)

        tool_context.repo.get_contents.assert_called_once_with("")
        assert "README.md" in result
        assert "brain/" in result

    def test_lists_subdirectory(self, tool_context: ToolContext) -> None:
        """path param is forwarded to get_contents so subdirs work."""
        f1 = MagicMock()
        f1.name = "tools.py"
        f1.type = "file"
        tool_context.repo.get_contents.return_value = [f1]

        result = execute_tool("list_files", {"path": "brain"}, tool_context)

        tool_context.repo.get_contents.assert_called_once_with("brain")
        assert "tools.py" in result

    def test_returns_error_on_failure(self, tool_context: ToolContext) -> None:
        tool_context.repo.get_contents.side_effect = Exception("Not found")
        result = execute_tool("list_files", {"path": "nonexistent"}, tool_context)
        assert "error" in result.lower()


class TestMergePrTool:
    """merge_pr is critic-only and squash-merges an approved PR."""

    def _critic_ctx(self, tmp_path: Path) -> ToolContext:
        memory_root = tmp_path / "memory"
        (memory_root / "shared" / "costs").mkdir(parents=True)
        (memory_root / "galadriel").mkdir(parents=True)
        return ToolContext(
            repo=MagicMock(),
            memory_root=memory_root,
            agent_name="galadriel",
            agent_role="critic",
            notify_fn=MagicMock(),
            costs_dir=memory_root / "shared" / "costs",
        )

    def test_merges_pr_as_critic(self, tmp_path: Path) -> None:
        ctx = self._critic_ctx(tmp_path)
        mock_pr = MagicMock()
        ctx.repo.get_pull.return_value = mock_pr

        result = execute_tool("merge_pr", {"pr_number": 55}, ctx)

        ctx.repo.get_pull.assert_called_once_with(55)
        mock_pr.merge.assert_called_once_with(merge_method="squash")
        assert "merged" in result.lower()

    def test_non_critic_cannot_merge(self, tool_context: ToolContext) -> None:
        """Non-critic role must be rejected without calling the API."""
        ctx = ToolContext(
            repo=tool_context.repo,
            memory_root=tool_context.memory_root,
            agent_name="gimli",
            agent_role="builder",
            notify_fn=tool_context.notify_fn,
            costs_dir=tool_context.costs_dir,
        )
        result = execute_tool("merge_pr", {"pr_number": 55}, ctx)

        ctx.repo.get_pull.assert_not_called()
        assert "critic" in result.lower() or "only" in result.lower()

    def test_returns_error_on_failure(self, tmp_path: Path) -> None:
        ctx = self._critic_ctx(tmp_path)
        ctx.repo.get_pull.side_effect = Exception("API error")
        result = execute_tool("merge_pr", {"pr_number": 55}, ctx)
        assert "error" in result.lower()


class TestCloseIssueTool:
    """close_issue edits issue state to closed and optionally posts a comment."""

    def test_closes_issue(self, tool_context: ToolContext) -> None:
        mock_issue = MagicMock()
        tool_context.repo.get_issue.return_value = mock_issue

        result = execute_tool("close_issue", {"issue_number": 7}, tool_context)

        tool_context.repo.get_issue.assert_called_once_with(7)
        mock_issue.edit.assert_called_once_with(state="closed")
        assert "closed" in result.lower()

    def test_posts_comment_if_provided(self, tool_context: ToolContext) -> None:
        mock_issue = MagicMock()
        tool_context.repo.get_issue.return_value = mock_issue

        execute_tool(
            "close_issue",
            {"issue_number": 7, "comment": "Fixed in PR #12."},
            tool_context,
        )

        mock_issue.create_comment.assert_called_once_with("Fixed in PR #12.")
        mock_issue.edit.assert_called_once_with(state="closed")

    def test_returns_error_on_failure(self, tool_context: ToolContext) -> None:
        tool_context.repo.get_issue.side_effect = Exception("Not found")
        result = execute_tool("close_issue", {"issue_number": 999}, tool_context)
        assert "error" in result.lower()


class TestClosePrTool:
    """close_pr edits PR state to closed (without merging) and optionally comments."""

    def test_closes_pr(self, tool_context: ToolContext) -> None:
        mock_pr = MagicMock()
        tool_context.repo.get_pull.return_value = mock_pr

        result = execute_tool("close_pr", {"pr_number": 8}, tool_context)

        tool_context.repo.get_pull.assert_called_once_with(8)
        mock_pr.edit.assert_called_once_with(state="closed")
        assert "closed" in result.lower()

    def test_posts_comment_if_provided(self, tool_context: ToolContext) -> None:
        mock_pr = MagicMock()
        tool_context.repo.get_pull.return_value = mock_pr

        execute_tool(
            "close_pr",
            {"pr_number": 8, "comment": "Won't fix — out of scope."},
            tool_context,
        )

        mock_pr.create_issue_comment.assert_called_once_with("Won't fix — out of scope.")
        mock_pr.edit.assert_called_once_with(state="closed")

    def test_returns_error_on_failure(self, tool_context: ToolContext) -> None:
        tool_context.repo.get_pull.side_effect = Exception("Not found")
        result = execute_tool("close_pr", {"pr_number": 999}, tool_context)
        assert "error" in result.lower()


class TestPushToPrTool:
    """push_to_pr pushes additional commits to an existing PR's branch.

    This is the correct way to address review feedback — rather than opening a
    second PR that 'fixes' the first one. The tool looks up the PR's head branch
    and commits each file there using the same create/update logic as create_pr.
    """

    def test_pushes_new_file_to_existing_pr(self, tool_context: ToolContext) -> None:
        """Files are committed to the PR's head branch, not main."""
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_pr.head.ref = "gimli/add-reviewer"
        tool_context.repo.get_pull.return_value = mock_pr
        # File doesn't exist yet on the branch
        tool_context.repo.get_contents.side_effect = GithubException(404, "Not Found", None)

        result = execute_tool(
            "push_to_pr",
            {
                "pr_number": 42,
                "files": [{"path": "brain/reviewer.py", "content": "# stub"}],
            },
            tool_context,
        )

        tool_context.repo.get_pull.assert_called_once_with(42)
        tool_context.repo.create_file.assert_called_once_with(
            path="brain/reviewer.py",
            message="Add brain/reviewer.py",
            content="# stub",
            branch="gimli/add-reviewer",
        )
        assert "42" in result

    def test_updates_existing_file_on_pr_branch(self, tool_context: ToolContext) -> None:
        """If the file already exists on the branch, update_file is called."""
        mock_pr = MagicMock()
        mock_pr.number = 43
        mock_pr.head.ref = "samwise/fix-tests"
        tool_context.repo.get_pull.return_value = mock_pr
        existing = MagicMock()
        existing.sha = "ff0011"
        tool_context.repo.get_contents.return_value = existing

        result = execute_tool(
            "push_to_pr",
            {
                "pr_number": 43,
                "files": [{"path": "tests/test_foo.py", "content": "fixed"}],
            },
            tool_context,
        )

        tool_context.repo.update_file.assert_called_once_with(
            path="tests/test_foo.py",
            message="Update tests/test_foo.py",
            content="fixed",
            sha="ff0011",
            branch="samwise/fix-tests",
        )
        tool_context.repo.create_file.assert_not_called()
        assert "43" in result

    def test_push_to_pr_in_schema(self) -> None:
        """push_to_pr must appear in TOOL_SCHEMAS."""
        names = {s["name"] for s in TOOL_SCHEMAS}
        assert "push_to_pr" in names

    def test_returns_error_on_failure(self, tool_context: ToolContext) -> None:
        tool_context.repo.get_pull.side_effect = Exception("API error")
        result = execute_tool("push_to_pr", {"pr_number": 99, "files": []}, tool_context)
        assert "error" in result.lower()
