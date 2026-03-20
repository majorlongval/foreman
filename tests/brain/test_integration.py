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
    def test_complete_cycle_produces_journal_entry(self, integration_env) -> None:
        # Mock LLM — Elrond makes exactly 1 call
        elrond_resp = MagicMock()
        elrond_resp.text = (
            '{"decision": "Research models", "action_plan": "List available models",'
            '"phases": [[{"agent": "gandalf", "task": "scout models", "deliverable": "notes.md"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100

        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 100
        executor_resp.output_tokens = 40

        mock_llm = MagicMock()
        mock_llm.complete.return_value = elrond_resp
        mock_llm.complete_with_tools.return_value = executor_resp

        outcome = run_cycle(
            config=integration_env["config"],
            repo=integration_env["mock_repo"],
            llm=mock_llm,
            memory_root=integration_env["memory_root"],
            philosophy="Be good. Grow.",
            repo_root=integration_env["repo_root"],
        )
        assert outcome.status == "success"
        
        # Verify journal was written
        journal_dir = integration_env["memory_root"] / "shared" / "journal"
        journal_files = [f for f in journal_dir.iterdir() if f.suffix == ".md"]
        assert len(journal_files) >= 1
        assert "Research models" in journal_files[0].read_text()

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
        # Line length fix: break raw_message into multi-line dict
        resp1.raw_message = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "list_files", "arguments": '{"path": "brain/"}'}
                }
            ]
        }
        resp1.input_tokens = 100
        resp1.output_tokens = 20

        # Round 2: read_file
        resp2 = MagicMock()
        tool_call2 = MagicMock()
        tool_call2.id = "call_2"
        tool_call2.function.name = "read_file"
        tool_call2.function.arguments = '{"path": "brain/tools.py"}'
        resp2.tool_calls = [tool_call2]
        resp2.raw_message = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "brain/tools.py"}'}
                }
            ]
        }
        resp2.input_tokens = 150
        resp2.output_tokens = 20

        # Round 3: Done
        resp3 = MagicMock()
        resp3.tool_calls = []
        resp3.text = "I have listed the files and read tools.py."
        resp3.input_tokens = 200
        resp3.output_tokens = 30

        mock_llm.complete_with_tools.side_effect = [resp1, resp2, resp3]

        # Fix: add notify_fn
        tool_ctx = ToolContext(
            repo=integration_env["mock_repo"],
            memory_root=integration_env["memory_root"],
            agent_name="gandalf",
            notify_fn=lambda x: True,
            costs_dir=integration_env["memory_root"] / "shared" / "costs",
        )
        
        with patch("brain.executor.execute_tool") as mock_exec_tool:
            mock_exec_tool.side_effect = ["tools.py", "def some_tool(): pass"]
            
            result = execute_action(
                task="Audit the tools",
                agent_name="gandalf",
                decision="Improve code quality",
                llm=mock_llm,
                tool_ctx=tool_ctx,
                model="test/model"
            )

        assert "read tools.py" in result.summary
        assert mock_llm.complete_with_tools.call_count == 3

    def test_cross_phase_integration(self, integration_env) -> None:
        """Test that an action in phase 1 is visible to an agent in phase 2."""
        mock_llm = MagicMock()
        
        # Elrond response
        elrond_resp = MagicMock()
        elrond_resp.text = json.dumps({
            "decision": "Collab",
            "action_plan": "P1 plans, P2 acts",
            "phases": [
                [{"agent": "gandalf", "task": "Write plan", "deliverable": "shared/plan.md"}],
                [{"agent": "gimli", "task": "Read plan", "deliverable": "memory/gimli/done.md"}]
            ],
            "flag_for_jord": False,
            "flag_reason": ""
        })
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp

        # Gandalf (Phase 1)
        g_resp1 = MagicMock()
        g_tc = MagicMock()
        g_tc.id = "g1"
        g_tc.function.name = "write_memory"
        g_tc.function.arguments = json.dumps({"path": "shared/plan.md", "content": "The Plan"})
        g_resp1.tool_calls = [g_tc]
        g_resp1.raw_message = {"role": "assistant", "tool_calls": [{"id": "g1", "type": "function", "function": {"name": "write_memory", "arguments": g_tc.function.arguments}}]}
        g_resp1.input_tokens = 100
        g_resp1.output_tokens = 50
        
        g_resp2 = MagicMock()
        g_resp2.tool_calls = []
        g_resp2.text = "Plan written."
        g_resp2.input_tokens = 120
        g_resp2.output_tokens = 10

        # Gimli (Phase 2)
        m_resp1 = MagicMock()
        m_tc = MagicMock()
        m_tc.id = "m1"
        m_tc.function.name = "read_memory"
        m_tc.function.arguments = json.dumps({"path": "shared/plan.md"})
        m_resp1.tool_calls = [m_tc]
        m_resp1.raw_message = {"role": "assistant", "tool_calls": [{"id": "m1", "type": "function", "function": {"name": "read_memory", "arguments": m_tc.function.arguments}}]}
        m_resp1.input_tokens = 100
        m_resp1.output_tokens = 50

        m_resp2 = MagicMock()
        m_resp2.tool_calls = []
        m_resp2.text = "Read the plan."
        m_resp2.input_tokens = 150
        m_resp2.output_tokens = 10

        mock_llm.complete_with_tools.side_effect = [g_resp1, g_resp2, m_resp1, m_resp2]

        outcome = run_cycle(
            config=integration_env["config"],
            repo=integration_env["mock_repo"],
            llm=mock_llm,
            memory_root=integration_env["memory_root"],
            philosophy="Be good.",
            repo_root=integration_env["repo_root"],
        )

        assert outcome.status == "success"
        # Verify Gimli could read the plan
        plan_file = integration_env["memory_root"] / "shared" / "plan.md"
        assert plan_file.read_text() == "The Plan"

    def test_executor_respects_budget_during_loop(self, integration_env) -> None:
        """Test that the executor stops if it hits the budget limit during tool rounds."""
        mock_llm = MagicMock()
        
        # Round 1 tool call
        resp1 = MagicMock()
        tc = MagicMock()
        tc.id = "tc1"
        tc.function.name = "list_files"
        tc.function.arguments = '{}'
        resp1.tool_calls = [tc]
        resp1.raw_message = {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]}
        # High token counts to hit budget
        resp1.input_tokens = 100000
        resp1.output_tokens = 100000
        
        mock_llm.complete_with_tools.return_value = resp1

        tool_ctx = ToolContext(
            repo=integration_env["mock_repo"],
            memory_root=integration_env["memory_root"],
            agent_name="gandalf",
            notify_fn=lambda x: True,
            costs_dir=integration_env["memory_root"] / "shared" / "costs",
            budget_limit=0.01  # Very low budget
        )
        
        result = execute_action(
            task="Spend money",
            agent_name="gandalf",
            decision="Test budget",
            llm=mock_llm,
            tool_ctx=tool_ctx,
            model="gpt-4"
        )
        
        assert "budget limit" in result.summary.lower()
        assert mock_llm.complete_with_tools.call_count == 1

    def test_safety_gate_blocks_non_critic(self, integration_env) -> None:
        """Verify that a non-critic agent cannot use approve_pr/merge_pr."""
        # This is handled in tools.py, but we test it through execute_tool or execute_action
        from brain.tools import execute_tool
        
        tool_ctx = ToolContext(
            repo=integration_env["mock_repo"],
            memory_root=integration_env["memory_root"],
            agent_name="gandalf",
            notify_fn=lambda x: True,
            costs_dir=integration_env["memory_root"] / "shared" / "costs",
            agent_role="scout" # Not critic
        )
        
        res = execute_tool("approve_pr", {"pr_number": 1, "comment": "looks good"}, tool_ctx)
        assert "Error: only the critic role" in res
        
        res = execute_tool("merge_pr", {"pr_number": 1}, tool_ctx)
        assert "Error: only the critic role" in res
