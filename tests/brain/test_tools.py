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
