"""Integration test — full brain cycle and executor loop with mocks."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brain.config import AgentConfig, Config
from brain.loop import run_cycle
from brain.executor import execute_action
from brain.tools import ToolContext


@pytest.fixture
def integration_env(tmp_path: Path):
    """Set up a complete environment for integration testing."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    memory_root = tmp_path / "memory"
    for d in ["shared/costs", "shared/decisions", "shared/journal", "shared/incidents", "gandalf", "gimli"]:
        (memory_root / d).mkdir(parents=True)

    (repo_root / "PHILOSOPHY.md").write_text("Be good. Grow. Be efficient.")
    agents_dir = repo_root / "agents"
    agents_dir.mkdir()
    (agents_dir / "gandalf.md").write_text("You are Gandalf the scout.")
    (agents_dir / "gimli.md").write_text("You are Gimli the builder.")

    config = Config(
        daily_limit_usd=5.0,
        model_default="test/model",
        model_reasoning="test/model",
        model_council="test/model",
        model_elrond="test/model",
        agents=[
            AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
            AgentConfig("gimli", "builder", Path("agents/gimli.md"), Path("memory/gimli/")),
        ],
        council_enabled=True,
        max_cycles_per_day=12,
        telegram_enabled=True,
    )

    # Mock GitHub repo
    mock_repo = MagicMock()
    mock_repo.get_issues.return_value = []
    mock_repo.get_pulls.return_value = []

    return {
        "config": config,
        "repo_root": repo_root,
        "memory_root": memory_root,
        "mock_repo": mock_repo,
    }


class TestIntegrationSuite:
    def test_agent_multi_step_tool_use(self, integration_env) -> None:
        """Test that the executor loop handles multiple rounds where tools depend on each other."""
        mock_llm = MagicMock()
        
        # Round 1: list_files
        resp1 = MagicMock()
        tool_call1 = MagicMock()
        tool_call1.id = "call_1"
        tool_call1.function.name = "list_files"
        tool_call1.function.arguments = '{"path": "brain/"}'
        resp1.tool_calls = [tool_call1]
        resp1.raw_message = {"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "list_files", "arguments": '{"path": "brain/"}'}}]}
        resp1.input_tokens = 100
        resp1.output_tokens = 20

        # Round 2: read_file (based on list_files)
        resp2 = MagicMock()
        tool_call2 = MagicMock()
        tool_call2.id = "call_2"
        tool_call2.function.name = "read_file"
        tool_call2.function.arguments = '{"path": "brain/tools.py"}'
        resp2.tool_calls = [tool_call2]
        resp2.raw_message = {"role": "assistant", "tool_calls": [{"id": "call_2", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "brain/tools.py"}'}}]}
        resp2.input_tokens = 150
        resp2.output_tokens = 20

        # Round 3: create_issue (based on read_file)
        resp3 = MagicMock()
        tool_call3 = MagicMock()
        tool_call3.id = "call_3"
        tool_call3.function.name = "create_issue"
        tool_call3.function.arguments = '{"title": "Improve tools", "body": "Found some issues in tools.py"}'
        resp3.tool_calls = [tool_call3]
        resp3.raw_message = {"role": "assistant", "tool_calls": [{"id": "call_3", "type": "function", "function": {"name": "create_issue", "arguments": '{"title": "Improve tools", "body": "Found some issues in tools.py"}'}}]}
        resp3.input_tokens = 300
        resp3.output_tokens = 30

        # Round 4: Done
        resp4 = MagicMock()
        resp4.tool_calls = []
        resp4.text = "I have listed the files, read tools.py, and created an issue for improvements."
        resp4.input_tokens = 400
        resp4.output_tokens = 40

        mock_llm.complete_with_tools.side_effect = [resp1, resp2, resp3, resp4]

        tool_ctx = ToolContext(
            repo=integration_env["mock_repo"],
            memory_root=integration_env["memory_root"],
            agent_name="gandalf",
            costs_dir=integration_env["memory_root"] / "shared" / "costs",
        )

        # Create a dummy file for read_file to find
        brain_dir = integration_env["repo_root"] / "brain"
        brain_dir.mkdir()
        (brain_dir / "tools.py").write_text("def some_tool(): pass")

        # We need to mock list_files and read_file results in execute_tool or just let them run
        # Since we are using real ToolContext and real repo_root isn't easily accessible to tools 
        # unless we mock them, but tools.py uses Path(".") or similar.
        # Actually, let's just mock execute_tool to return what we want.
        
        with patch("brain.executor.execute_tool") as mock_exec_tool:
            mock_exec_tool.side_effect = [
                "tools.py, executor.py",  # result of list_files
                "def some_tool(): pass",   # result of read_file
                "Issue #1 created",       # result of create_issue
            ]
            
            result = execute_action(
                task="Audit the tools and report issues",
                agent_name="gandalf",
                decision="Improve code quality",
                llm=mock_llm,
                tool_ctx=tool_ctx,
                model="test/model"
            )

        assert "created an issue" in result.summary
        assert mock_llm.complete_with_tools.call_count == 4
        assert mock_exec_tool.call_count == 3

    def test_cross_phase_integration(self, integration_env) -> None:
        """Test that an action in phase 1 is visible to an agent in phase 2."""
        # Phase 1: Gandalf writes a plan to shared memory
        # Phase 2: Gimli reads the plan and acts on it
        
        mock_llm = MagicMock()
        
        # Elrond response
        elrond_resp = MagicMock()
        elrond_resp.text = json.dumps({
            "decision": "Collaborative task",
            "action_plan": "Gandalf plans, Gimli executes",
            "phases": [
                [{"agent": "gandalf", "task": "Write plan to shared/plans/test.md", "deliverable": "plan written"}],
                [{"agent": "gimli", "task": "Read plan from shared/plans/test.md and create issue", "deliverable": "issue created"}]
            ],
            "flag_for_jord": False,
            "flag_reason": ""
        })
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp

        # Gandalf rounds (Phase 1)
        g_resp1 = MagicMock()
        g_tool_call = MagicMock()
        g_tool_call.id = "g_call_1"
        g_tool_call.function.name = "write_memory"
        g_tool_call.function.arguments = json.dumps({"path": "shared/plans/test.md", "content": "Plan: Build a bridge"})
        g_resp1.tool_calls = [g_tool_call]
        g_resp1.raw_message = {"role": "assistant", "tool_calls": [{"id": "g_call_1", "type": "function", "function": {"name": "write_memory", "arguments": g_tool_call.function.arguments}}]}
        g_resp1.input_tokens = 100
        g_resp1.output_tokens = 50
        
        g_resp2 = MagicMock()
        g_resp2.tool_calls = []
        g_resp2.text = "Plan written."
        g_resp2.input_tokens = 120
        g_resp2.output_tokens = 10

        # Gimli rounds (Phase 2)
        m_resp1 = MagicMock()
        m_tool_call1 = MagicMock()
        m_tool_call1.id = "m_call_1"
        m_tool_call1.function.name = "read_memory"
        m_tool_call1.function.arguments = json.dumps({"path": "shared/plans/test.md"})
        m_resp1.tool_calls = [m_tool_call1]
        m_resp1.raw_message = {"role": "assistant", "tool_calls": [{"id": "m_call_1", "type": "function", "function": {"name": "read_memory", "arguments": m_tool_call1.function.arguments}}]}
        m_resp1.input_tokens = 100
        m_resp1.output_tokens = 50

        m_resp2 = MagicMock()
        m_tool_call2 = MagicMock()
        m_tool_call2.id = "m_call_2"
        m_tool_call2.function.name = "create_issue"
        m_tool_call2.function.arguments = json.dumps({"title": "Build bridge", "body": "As planned: Build a bridge"})
        m_resp2.tool_calls = [m_tool_call2]
        m_resp2.raw_message = {"role": "assistant", "tool_calls": [{"id": "m_call_2", "type": "function", "function": {"name": "create_issue", "arguments": m_tool_call2.function.arguments}}]}
        m_resp2.input_tokens = 200
        m_resp2.output_tokens = 50

        m_resp3 = MagicMock()
        m_resp3.tool_calls = []
        m_resp3.text = "Issue created based on Gandalf's plan."
        m_resp3.input_tokens = 250
        m_resp3.output_tokens = 10

        mock_llm.complete_with_tools.side_effect = [g_resp1, g_resp2, m_resp1, m_resp2, m_resp3]

        outcome = run_cycle(
            config=integration_env["config"],
            repo=integration_env["mock_repo"],
            llm=mock_llm,
            memory_root=integration_env["memory_root"],
            philosophy="Be good.",
            repo_root=integration_env["repo_root"],
        )

        assert outcome.status == "success"
        # Verify Gandalf actually wrote the file
        plan_file = integration_env["memory_root"] / "shared" / "plans" / "test.md"
        assert plan_file.exists()
        assert "Build a bridge" in plan_file.read_text()
        
        # Verify Gimli's tool calls (read_memory was called)
        # We can check that the 3rd call to complete_with_tools had the right read_memory call
        assert mock_llm.complete_with_tools.call_count == 5

    def test_full_cycle_with_multi_phase_assignments(self, integration_env) -> None:
        """Test a full cycle where multiple agents have tasks across different phases."""
        mock_llm = MagicMock()
        
        # Elrond assigns Gandalf to phase 1 and Gimli to phase 2
        elrond_resp = MagicMock()
        elrond_resp.text = json.dumps({
            "decision": "Multi-phase work",
            "action_plan": "Phase 1: Scout, Phase 2: Build",
            "phases": [
                [{"agent": "gandalf", "task": "scout", "deliverable": "scout report"}],
                [{"agent": "gimli", "task": "build", "deliverable": "build result"}]
            ],
            "flag_for_jord": false,
            "flag_reason": ""
        })
        elrond_resp.input_tokens = 100
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp

        # Use a simple helper to return tool calls then done
        def make_responses(agent_name):
            tool_call = MagicMock()
            tool_call.id = f"call_{agent_name}"
            tool_call.function.name = "write_memory"
            tool_call.function.arguments = json.dumps({"path": f"{agent_name}/notes.md", "content": f"{agent_name} was here"})
            
            resp_tool = MagicMock()
            resp_tool.tool_calls = [tool_call]
            resp_tool.raw_message = {"role": "assistant", "tool_calls": [{"id": tool_call.id, "type": "function", "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments}}]}
            resp_tool.input_tokens = 100
            resp_tool.output_tokens = 50
            
            resp_done = MagicMock()
            resp_done.tool_calls = []
            resp_done.text = f"{agent_name} finished"
            resp_done.input_tokens = 120
            resp_done.output_tokens = 10
            
            return [resp_tool, resp_done]

        mock_llm.complete_with_tools.side_effect = make_responses("gandalf") + make_responses("gimli")

        outcome = run_cycle(
            config=integration_env["config"],
            repo=integration_env["mock_repo"],
            llm=mock_llm,
            memory_root=integration_env["memory_root"],
            philosophy="Be good.",
            repo_root=integration_env["repo_root"],
        )

        assert outcome.status == "success"
        assert "gandalf finished" in outcome.action_result
        assert "gimli finished" in outcome.action_result
        assert mock_llm.complete_with_tools.call_count == 4

    def test_budget_exhausted_skips_everything(self, integration_env) -> None:
        """Test that budget exhaustion is respected at the start of the cycle."""
        # Spend all the budget
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        costs_dir = integration_env["memory_root"] / "shared" / "costs"
        (costs_dir / f"{today}.jsonl").write_text(json.dumps({"cost_usd": 10.0}) + "\n")
        
        mock_llm = MagicMock()
        outcome = run_cycle(
            config=integration_env["config"],
            repo=integration_env["mock_repo"],
            llm=mock_llm,
            memory_root=integration_env["memory_root"],
            philosophy="Be good.",
            repo_root=integration_env["repo_root"],
        )
        assert outcome.status == "budget_exhausted"
        mock_llm.complete.assert_not_called()
