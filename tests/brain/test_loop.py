"""Tests for brain.loop — the Wiggum loop (one cycle)."""

import itertools
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from brain.loop import run_cycle, CycleOutcome
from brain.config import Config, AgentConfig

# Standard Elrond response for tests — one LLM call, no deliberation
_ELROND_RESPONSE = (
    '{"decision": "build it", "action_plan": "step 1",'
    '"phases": [],'
    '"flag_for_jord": false, "flag_reason": ""}'
)


def make_config() -> Config:
    return Config(
        daily_limit_usd=5.0,
        model_default="gemini/gemini-2.5-flash",
        model_reasoning="gemini/gemini-2.5-pro",
        model_council="anthropic/claude-sonnet-4-6",
        model_elrond="gemini/gemini-3-pro-preview",
        agents=[
            AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
            AgentConfig("gimli", "builder", Path("agents/gimli.md"), Path("memory/gimli/")),
        ],
        council_enabled=True,
        max_cycles_per_day=12,
        telegram_enabled=True,
    )


@pytest.fixture
def cycle_env(tmp_path: Path):
    """Set up a minimal environment for run_cycle tests."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    memory_root = tmp_path / "memory"
    for d in ["shared/costs", "shared/decisions", "shared/journal", "shared/incidents",
              "gandalf", "gimli"]:
        (memory_root / d).mkdir(parents=True)

    # Write philosophy
    (repo_root / "PHILOSOPHY.md").write_text("Be good. Grow.")
    # Write agent identities
    agents_dir = repo_root / "agents"
    agents_dir.mkdir()
    (agents_dir / "gandalf.md").write_text("You are Gandalf.")
    (agents_dir / "gimli.md").write_text("You are Gimli.")

    return {
        "config": make_config(),
        "repo_root": repo_root,
        "memory_root": memory_root,
        "philosophy": "Be good. Grow.",
    }


def _make_elrond_resp() -> MagicMock:
    """Build a mock LLM response for Elrond's single orchestration call."""
    resp = MagicMock()
    resp.text = _ELROND_RESPONSE
    resp.input_tokens = 200
    resp.output_tokens = 100
    return resp


def _make_executor_side_effect() -> itertools.cycle:
    """Build a repeating side_effect for complete_with_tools that satisfies deliverable enforcement.

    The executor now requires at least one tool call before accepting a done response.
    We cycle through: [tool_call_resp, done_resp, tool_call_resp, done_resp, ...]
    so any number of agents × 2 rounds works without running out of responses.
    """
    tool_call = MagicMock()
    tool_call.id = "call_wm"
    tool_call.function.name = "write_memory"
    tool_call.function.arguments = '{"agent_name": "agent", "filename": "cycle_notes.md", "content": "done"}'

    tool_resp = MagicMock()
    tool_resp.tool_calls = [tool_call]
    tool_resp.text = ""
    tool_resp.input_tokens = 100
    tool_resp.output_tokens = 40
    tool_resp.raw_message = {"role": "assistant", "tool_calls": [
        {"id": "call_wm", "type": "function", "function": {
            "name": "write_memory",
            "arguments": '{"agent_name": "agent", "filename": "cycle_notes.md", "content": "done"}',
        }}
    ]}

    done_resp = MagicMock()
    done_resp.tool_calls = []
    done_resp.text = "Done."
    done_resp.input_tokens = 60
    done_resp.output_tokens = 10

    return itertools.cycle([tool_resp, done_resp])


def _make_executor_resp() -> MagicMock:
    """Convenience wrapper — returns a MagicMock pre-wired with the cycle side_effect.

    Usage: mock_llm.complete_with_tools.side_effect = _make_executor_resp().side_effect
    """
    m = MagicMock()
    m.side_effect = _make_executor_side_effect()
    return m


class TestCycleOutcome:
    def test_budget_exhausted_outcome(self) -> None:
        outcome = CycleOutcome(
            status="budget_exhausted",
            decision="",
            action_result="",
            cost=0.0,
            error=None,
        )
        assert outcome.status == "budget_exhausted"

    def test_success_outcome(self) -> None:
        outcome = CycleOutcome(
            status="success",
            decision="Research new models",
            action_result="Created issue #100",
            cost=0.25,
            error=None,
        )
        assert outcome.status == "success"
        assert outcome.cost == 0.25

    def test_error_outcome(self) -> None:
        outcome = CycleOutcome(
            status="error",
            decision="",
            action_result="",
            cost=0.0,
            error="LLM API returned 500",
        )
        assert outcome.error is not None


class TestRunCycleBudgetExhausted:
    def test_exits_early_when_budget_spent(self, cycle_env) -> None:
        import json
        from datetime import datetime, timezone
        # Write cost entries exceeding the budget
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        costs_dir = cycle_env["memory_root"] / "shared" / "costs"
        (costs_dir / f"{today}.jsonl").write_text(
            json.dumps({"cost_usd": 10.0}) + "\n"
        )
        mock_repo = MagicMock()
        mock_llm = MagicMock()

        outcome = run_cycle(
            config=cycle_env["config"],
            repo=mock_repo,
            llm=mock_llm,
            memory_root=cycle_env["memory_root"],
            philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "budget_exhausted"
        mock_llm.complete.assert_not_called()


class TestRunCycleSuccess:
    def test_runs_council_and_writes_journal(self, cycle_env) -> None:
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []

        mock_llm = MagicMock()
        # Elrond makes exactly 1 LLM call — return Elrond response
        elrond_resp = MagicMock()
        elrond_resp.text = '{"decision": "build it", "action_plan": "step 1", "phases": [], "flag_for_jord": false, "flag_reason": ""}'
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()

        outcome = run_cycle(
            config=cycle_env["config"],
            repo=mock_repo,
            llm=mock_llm,
            memory_root=cycle_env["memory_root"],
            philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        assert "build" in outcome.decision.lower()
        # Journal should have been written
        journal_files = list((cycle_env["memory_root"] / "shared" / "journal").glob("*.md"))
        assert len(journal_files) >= 1


class TestRunCycleInbox:
    def test_inbox_cleared_after_successful_cycle(self, cycle_env) -> None:
        """INBOX.md must be empty after a successful cycle."""
        inbox = cycle_env["repo_root"] / "INBOX.md"
        inbox.write_text("Please diversify your perspectives.")

        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_elrond_resp()
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        assert inbox.read_text() == ""

    def test_cycle_succeeds_without_inbox(self, cycle_env) -> None:
        """Cycle completes normally when INBOX.md does not exist."""
        assert not (cycle_env["repo_root"] / "INBOX.md").exists()

        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_elrond_resp()
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"


class TestRunCycleIncidentNotification:
    def test_notify_called_on_survey_failure(self, cycle_env) -> None:
        """When the survey raises, notify_fn is called with the incident content."""
        mock_repo = MagicMock()
        mock_llm = MagicMock()
        notify_fn = MagicMock(return_value=True)

        with patch("brain.loop.gather_survey", side_effect=Exception("Survey exploded")):
            outcome = run_cycle(
                config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
                memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
                repo_root=cycle_env["repo_root"], notify_fn=notify_fn,
            )

        assert outcome.status == "error"
        notify_fn.assert_called_once()
        assert "Survey exploded" in notify_fn.call_args[0][0]


class TestRunCycleOutbox:
    def _make_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_elrond_resp()
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()
        return mock_llm

    def test_outbox_triggers_notification_and_is_cleared(self, cycle_env) -> None:
        """When OUTBOX.md has content, notify_fn is called with it and the file is cleared."""
        outbox = cycle_env["repo_root"] / "OUTBOX.md"
        outbox.write_text("Jord, we have a question about Issue #100.")

        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        notify_fn = MagicMock(return_value=True)

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=self._make_llm(),
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"], notify_fn=notify_fn,
        )
        assert outcome.status == "success"
        notify_fn.assert_called_once()
        assert "question about Issue #100" in notify_fn.call_args[0][0]
        assert outbox.read_text() == ""

    def test_cycle_succeeds_without_outbox(self, cycle_env) -> None:
        """Cycle completes normally when OUTBOX.md does not exist."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        notify_fn = MagicMock(return_value=True)

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=self._make_llm(),
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"], notify_fn=notify_fn,
        )
        assert outcome.status == "success"
        notify_fn.assert_not_called()


class TestRunCycleMultiAgentExecution:
    def test_each_agent_with_assignment_gets_executor_call(self, cycle_env) -> None:
        """When Elrond assigns tasks to both agents, complete_with_tools is called twice per agent (tool + done)."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        elrond_resp = MagicMock()
        elrond_resp.text = (
            '{"decision": "build and scout", "action_plan": "parallel work",'
            '"phases": [[{"agent": "gandalf", "task": "read brain/tools.py", "deliverable": "memory/gandalf/cycle_notes.md"},'
            '{"agent": "gimli", "task": "create an issue", "deliverable": "issue created"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        # 2 agents × 2 rounds each (tool call + done response) = 4 total
        assert mock_llm.complete_with_tools.call_count == 4

    def test_agent_without_assignment_skips_execution(self, cycle_env) -> None:
        """When Elrond only assigns one agent a task, only that agent's executor calls are made."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        elrond_resp = MagicMock()
        # Only gimli gets an assignment
        elrond_resp.text = (
            '{"decision": "build only", "action_plan": "gimli acts",'
            '"phases": [[{"agent": "gimli", "task": "create issue #5", "deliverable": "issue #5 created"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        # 1 agent × 2 rounds (tool call + done response) = 2 total
        assert mock_llm.complete_with_tools.call_count == 2


class TestRunCyclePhases:
    """Tests for the phases-based execution model."""

    def _make_executor_resp(self):
        return _make_executor_side_effect()

    def test_phase_2_runs_after_phase_1(self, cycle_env) -> None:
        """Phase 1 agents run before phase 2 agents — execution order is preserved."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        elrond_resp = MagicMock()
        # Two phases: phase 1 has gandalf, phase 2 has gimli
        elrond_resp.text = (
            '{"decision": "sequential work", "action_plan": "phase by phase",'
            '"phases": ['
            '  [{"agent": "gandalf", "task": "scout first", "deliverable": "memory/gandalf/cycle_notes.md"}],'
            '  [{"agent": "gimli", "task": "build after scout", "deliverable": "issue created"}]'
            '],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp

        call_order = []
        _cycle = _make_executor_side_effect()

        def executor_side_effect(**kwargs):
            # Record which agent was called based on the initial user message content.
            # Only log on round 1 (task message), not on pushback/tool-result rounds.
            messages = kwargs.get("messages", [])
            user_msg = next((m for m in messages if m["role"] == "user"), None)
            if user_msg and "scout first" in user_msg["content"] and "gandalf" not in call_order:
                call_order.append("gandalf")
            elif user_msg and "build after scout" in user_msg["content"] and "gimli" not in call_order:
                call_order.append("gimli")
            return next(_cycle)

        mock_llm.complete_with_tools.side_effect = executor_side_effect

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        assert call_order == ["gandalf", "gimli"], f"Expected gandalf before gimli, got: {call_order}"

    def test_single_agent_per_phase(self, cycle_env) -> None:
        """A phase with only one agent runs that agent exactly once."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        elrond_resp = MagicMock()
        elrond_resp.text = (
            '{"decision": "single agent", "action_plan": "gandalf only",'
            '"phases": [[{"agent": "gandalf", "task": "solo mission", "deliverable": "memory/gandalf/cycle_notes.md"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp
        mock_llm.complete_with_tools.side_effect = self._make_executor_resp()

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        assert mock_llm.complete_with_tools.call_count == 2  # 1 agent × 2 rounds

    def test_unknown_agent_in_phase_skipped(self, cycle_env) -> None:
        """If Elrond assigns a task to an unknown agent name, the cycle still succeeds."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        elrond_resp = MagicMock()
        # "aragorn" is not in the config (only gandalf, gimli)
        elrond_resp.text = (
            '{"decision": "delegate", "action_plan": "let aragorn handle it",'
            '"phases": [[{"agent": "aragorn", "task": "lead the charge", "deliverable": "battle won"},'
            '{"agent": "gandalf", "task": "cast spells", "deliverable": "memory/gandalf/cycle_notes.md"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        elrond_resp.input_tokens = 200
        elrond_resp.output_tokens = 100
        mock_llm.complete.return_value = elrond_resp
        mock_llm.complete_with_tools.side_effect = self._make_executor_resp()

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        # Aragorn is skipped; gandalf still runs (2 rounds: tool + done)
        assert outcome.status == "success"
        assert mock_llm.complete_with_tools.call_count == 2


class TestRunCycleSharedMemory:
    """Tests for expanded shared memory reading."""

    def _make_cycle_llm(self):
        """Build a minimal mock LLM that returns valid Elrond response for a full cycle."""
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _make_elrond_resp()
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()
        return mock_llm

    def test_shared_memory_includes_non_standard_subdir(self, cycle_env) -> None:
        """Files written to memory/shared/<custom>/ must appear in shared_memory_summary passed to council."""
        # Create a non-standard subdir under shared memory
        custom_dir = cycle_env["memory_root"] / "shared" / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "note.md").write_text("Custom shared note content.")

        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []

        captured_shared_memory: list[str] = []

        original_run_council = __import__("brain.council", fromlist=["run_council"]).run_council

        def capture_run_council(**kwargs):
            captured_shared_memory.append(kwargs.get("shared_memory_summary", ""))
            return original_run_council(**kwargs)

        from unittest.mock import patch
        with patch("brain.loop.run_council", side_effect=capture_run_council):
            outcome = run_cycle(
                config=cycle_env["config"], repo=mock_repo, llm=self._make_cycle_llm(),
                memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
                repo_root=cycle_env["repo_root"],
            )

        assert outcome.status == "success"
        assert len(captured_shared_memory) == 1
        assert "Custom shared note content." in captured_shared_memory[0]


class TestRunCycleCostPersistence:
    def test_successful_cycle_writes_cost_entry(self, cycle_env) -> None:
        """After a successful cycle, at least one cost entry must exist in today's JSONL."""
        import json
        from datetime import datetime, timezone

        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []

        mock_llm = MagicMock()
        elrond_resp = MagicMock()
        elrond_resp.text = '{"decision": "build it", "action_plan": "step 1", "phases": [], "flag_for_jord": false, "flag_reason": ""}'
        elrond_resp.input_tokens = 100
        elrond_resp.output_tokens = 50
        mock_llm.complete.return_value = elrond_resp
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()

        outcome = run_cycle(
            config=cycle_env["config"],
            repo=mock_repo,
            llm=mock_llm,
            memory_root=cycle_env["memory_root"],
            philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )

        assert outcome.status == "success"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cost_file = cycle_env["memory_root"] / "shared" / "costs" / f"{today}.jsonl"
        assert cost_file.exists(), "Cost JSONL file should be written after a successful cycle"
        lines = [line for line in cost_file.read_text().strip().split("\n") if line.strip()]
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["cost_usd"] >= 0.0


class TestRunCycleSurveyFailure:
    def test_logs_incident_on_survey_error(self, cycle_env) -> None:
        mock_repo = MagicMock()
        mock_repo.get_issues.side_effect = Exception("GitHub API down")
        mock_llm = MagicMock()

        # Survey should still succeed (it catches GitHub errors internally)
        # but with empty issues/PRs
        mock_llm.complete.return_value = _make_elrond_resp()
        mock_llm.complete_with_tools.side_effect = _make_executor_side_effect()

        run_cycle(
            config=cycle_env["config"],
            repo=mock_repo,
            llm=mock_llm,
            memory_root=cycle_env["memory_root"],
            philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
