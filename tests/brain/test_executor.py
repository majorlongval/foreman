"""Tests for brain.executor — tool-use execution loop."""

import json
import pytest
from unittest.mock import MagicMock, call
from pathlib import Path
from brain.executor import execute_action, to_openai_tools, ExecutionResult
from brain.tools import TOOL_SCHEMAS, ToolContext


@pytest.fixture
def tool_ctx(tmp_path: Path) -> ToolContext:
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


class TestToOpenAITools:
    def test_converts_schema_format(self) -> None:
        result = to_openai_tools(TOOL_SCHEMAS)
        assert len(result) == len(TOOL_SCHEMAS)
        for tool in result:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    def test_read_file_tool_converted(self) -> None:
        result = to_openai_tools(TOOL_SCHEMAS)
        read_file = next(t for t in result if t["function"]["name"] == "read_file")
        assert read_file["function"]["parameters"]["required"] == ["path"]


class TestExecuteActionNoTools:
    def test_empty_task_skips(self, tool_ctx: ToolContext) -> None:
        mock_llm = MagicMock()
        result = execute_action(
            task="", agent_name="gandalf", decision="explore",
            llm=mock_llm, tool_ctx=tool_ctx, model="test/model",
        )
        assert "skipping" in result.summary.lower()
        mock_llm.complete_with_tools.assert_not_called()


class TestExecuteActionTextResponse:
    def test_llm_returns_text_only(self, tool_ctx: ToolContext) -> None:
        """LLM decides no tool calls needed — just returns text."""
        mock_llm = MagicMock()
        response = MagicMock()
        response.tool_calls = []
        response.text = "I reviewed the situation and no action is needed right now."
        response.input_tokens = 200
        response.output_tokens = 80
        mock_llm.complete_with_tools.return_value = response

        result = execute_action(
            task="Review current state", agent_name="gandalf", decision="assess",
            llm=mock_llm, tool_ctx=tool_ctx, model="gemini/gemini-3-flash-preview",
        )
        assert isinstance(result, ExecutionResult)
        assert "no action" in result.summary.lower()
        assert result.cost_usd > 0.0


class TestExecuteActionWithToolCalls:
    def test_single_tool_call(self, tool_ctx: ToolContext) -> None:
        """LLM calls check_budget, gets result, then responds with text."""
        mock_llm = MagicMock()

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "check_budget"
        tool_call.function.arguments = "{}"

        first_response = MagicMock()
        first_response.tool_calls = [tool_call]
        first_response.text = ""
        first_response.input_tokens = 100
        first_response.output_tokens = 50
        first_response.raw_message = {"role": "assistant", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "check_budget", "arguments": "{}"}}
        ]}

        second_response = MagicMock()
        second_response.tool_calls = []
        second_response.text = "Budget is $5.00 remaining. All good."
        second_response.input_tokens = 100
        second_response.output_tokens = 30

        mock_llm.complete_with_tools.side_effect = [first_response, second_response]

        result = execute_action(
            task="Check the budget", agent_name="gandalf", decision="monitor",
            llm=mock_llm, tool_ctx=tool_ctx, model="test/model",
        )
        assert "$" in result.summary
        assert mock_llm.complete_with_tools.call_count == 2

    def test_write_memory_tool_call(self, tool_ctx: ToolContext) -> None:
        """LLM writes to shared memory via tool call."""
        mock_llm = MagicMock()

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "write_memory"
        tool_call.function.arguments = json.dumps({
            "path": "shared/decisions/test.md",
            "content": "We decided to explore.",
        })

        first_response = MagicMock()
        first_response.tool_calls = [tool_call]
        first_response.text = ""
        first_response.input_tokens = 100
        first_response.output_tokens = 50
        first_response.raw_message = {"role": "assistant", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {
                "name": "write_memory",
                "arguments": json.dumps({"path": "shared/decisions/test.md", "content": "We decided to explore."})
            }}
        ]}

        second_response = MagicMock()
        second_response.tool_calls = []
        second_response.text = "Decision recorded."
        second_response.input_tokens = 150
        second_response.output_tokens = 30

        mock_llm.complete_with_tools.side_effect = [first_response, second_response]

        result = execute_action(
            task="Write a decision", agent_name="gandalf", decision="document",
            llm=mock_llm, tool_ctx=tool_ctx, model="test/model",
        )
        assert (tool_ctx.memory_root / "shared" / "decisions" / "test.md").read_text() == "We decided to explore."

    def test_max_rounds_prevents_infinite_loop(self, tool_ctx: ToolContext) -> None:
        """Safety: stops after max_rounds even if LLM keeps calling tools."""
        mock_llm = MagicMock()

        tool_call = MagicMock()
        tool_call.id = "call_n"
        tool_call.function.name = "check_budget"
        tool_call.function.arguments = "{}"

        response = MagicMock()
        response.tool_calls = [tool_call]
        response.text = ""
        response.input_tokens = 100
        response.output_tokens = 50
        response.raw_message = {"role": "assistant", "tool_calls": [
            {"id": "call_n", "type": "function", "function": {"name": "check_budget", "arguments": "{}"}}
        ]}

        mock_llm.complete_with_tools.return_value = response

        result = execute_action(
            task="Check budget forever", agent_name="gandalf", decision="monitor",
            llm=mock_llm, tool_ctx=tool_ctx, model="test/model", max_rounds=3,
        )
        assert mock_llm.complete_with_tools.call_count == 3
        assert "max rounds" in result.summary.lower()


class TestExecuteActionLLMFailure:
    def test_llm_error_returns_error_message(self, tool_ctx: ToolContext) -> None:
        mock_llm = MagicMock()
        mock_llm.complete_with_tools.side_effect = Exception("API down")

        result = execute_action(
            task="Do something", agent_name="gandalf", decision="act",
            llm=mock_llm, tool_ctx=tool_ctx, model="test/model",
        )
        assert "error" in result.summary.lower()
        assert "API down" in result.summary
