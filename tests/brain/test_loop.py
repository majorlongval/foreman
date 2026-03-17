"""Tests for brain.loop — the Wiggum loop (one cycle)."""

import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path
from brain.loop import run_cycle, CycleOutcome
from brain.config import Config, AgentConfig


def make_config() -> Config:
    return Config(
        daily_limit_usd=5.0,
        model_default="gemini/gemini-2.5-flash",
        model_reasoning="gemini/gemini-2.5-pro",
        model_council="anthropic/claude-sonnet-4-6",
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
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "lets build", "proposed_action": "create issue"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "build it", "action_plan": "step 1", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 100
        executor_resp.output_tokens = 40
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp

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
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "ok", "proposed_action": "ok"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "ok", "action_plan": "ok", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 100
        executor_resp.output_tokens = 40
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp

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
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "ok", "proposed_action": "ok"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "ok", "action_plan": "ok", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 100
        executor_resp.output_tokens = 40
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp

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
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "ok", "proposed_action": "ok"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "ok", "action_plan": "ok", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 100
        executor_resp.output_tokens = 40
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp
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
        """When the chair assigns tasks to both agents, complete_with_tools is called once per agent."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "ok", "proposed_action": "ok"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        chair_resp.text = (
            '{"decision": "build and scout", "action_plan": "parallel work",'
            '"phases": [[{"agent": "gandalf", "task": "read brain/tools.py", "deliverable": "memory/gandalf/cycle_notes.md"},'
            '{"agent": "gimli", "task": "create an issue", "deliverable": "issue created"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 100
        executor_resp.output_tokens = 40
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        # Both gandalf and gimli have assignments — executor called twice
        assert mock_llm.complete_with_tools.call_count == 2

    def test_agent_without_assignment_skips_execution(self, cycle_env) -> None:
        """When the chair only assigns one agent a task, only one executor call is made."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "ok", "proposed_action": "ok"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        # Only gimli gets an assignment (phase with a single agent)
        chair_resp.text = (
            '{"decision": "build only", "action_plan": "gimli acts",'
            '"phases": [[{"agent": "gimli", "task": "create issue #5", "deliverable": "issue #5 created"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 100
        executor_resp.output_tokens = 40
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        assert mock_llm.complete_with_tools.call_count == 1


class TestRunCyclePhases:
    """Tests for the phases-based execution model."""

    def _make_agent_resp(self):
        resp = MagicMock()
        resp.text = '{"perspective": "ok", "proposed_action": "ok"}'
        resp.input_tokens = 100
        resp.output_tokens = 50
        return resp

    def _make_executor_resp(self):
        resp = MagicMock()
        resp.tool_calls = []
        resp.text = "Done."
        resp.input_tokens = 100
        resp.output_tokens = 40
        return resp

    def test_phase_2_runs_after_phase_1(self, cycle_env) -> None:
        """Phase 1 agents run before phase 2 agents — execution order is preserved."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        chair_resp = MagicMock()
        # Two phases: phase 1 has gandalf, phase 2 has gimli
        chair_resp.text = (
            '{"decision": "sequential work", "action_plan": "phase by phase",'
            '"phases": ['
            '  [{"agent": "gandalf", "task": "scout first", "deliverable": "memory/gandalf/cycle_notes.md"}],'
            '  [{"agent": "gimli", "task": "build after scout", "deliverable": "issue created"}]'
            '],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        mock_llm.complete.side_effect = [self._make_agent_resp(), self._make_agent_resp(), chair_resp]

        call_order = []

        def executor_side_effect(**kwargs):
            # Record which agent was called based on messages content
            messages = kwargs.get("messages", [])
            user_msg = next((m for m in messages if m["role"] == "user"), None)
            if user_msg and "scout first" in user_msg["content"]:
                call_order.append("gandalf")
            elif user_msg and "build after scout" in user_msg["content"]:
                call_order.append("gimli")
            resp = self._make_executor_resp()
            return resp

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
        chair_resp = MagicMock()
        chair_resp.text = (
            '{"decision": "single agent", "action_plan": "gandalf only",'
            '"phases": [[{"agent": "gandalf", "task": "solo mission", "deliverable": "memory/gandalf/cycle_notes.md"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        mock_llm.complete.side_effect = [self._make_agent_resp(), self._make_agent_resp(), chair_resp]
        mock_llm.complete_with_tools.return_value = self._make_executor_resp()

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        assert outcome.status == "success"
        assert mock_llm.complete_with_tools.call_count == 1

    def test_unknown_agent_in_phase_skipped(self, cycle_env) -> None:
        """If the chair assigns a task to an unknown agent name, the cycle still succeeds."""
        mock_repo = MagicMock()
        mock_repo.get_issues.return_value = []
        mock_repo.get_pulls.return_value = []
        mock_llm = MagicMock()
        chair_resp = MagicMock()
        # "aragorn" is not in the config (only gandalf, gimli)
        chair_resp.text = (
            '{"decision": "delegate", "action_plan": "let aragorn handle it",'
            '"phases": [[{"agent": "aragorn", "task": "lead the charge", "deliverable": "battle won"},'
            '{"agent": "gandalf", "task": "cast spells", "deliverable": "memory/gandalf/cycle_notes.md"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        mock_llm.complete.side_effect = [self._make_agent_resp(), self._make_agent_resp(), chair_resp]
        mock_llm.complete_with_tools.return_value = self._make_executor_resp()

        outcome = run_cycle(
            config=cycle_env["config"], repo=mock_repo, llm=mock_llm,
            memory_root=cycle_env["memory_root"], philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
        # Aragorn is skipped; gandalf still runs
        assert outcome.status == "success"
        assert mock_llm.complete_with_tools.call_count == 1


class TestRunCycleSharedMemory:
    """Tests for expanded shared memory reading."""

    def _make_cycle_llm(self):
        """Build a minimal mock LLM that returns valid responses for a full cycle."""
        mock_llm = MagicMock()
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "ok", "proposed_action": "ok"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "ok", "action_plan": "ok", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 100
        executor_resp.output_tokens = 40
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp
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
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "lets build", "proposed_action": "create issue"}'
        agent_resp.input_tokens = 100
        agent_resp.output_tokens = 50
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "build it", "action_plan": "step 1", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 200
        chair_resp.output_tokens = 100
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 150
        executor_resp.output_tokens = 60
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp

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
        lines = [l for l in cost_file.read_text().strip().split("\n") if l.strip()]
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
        agent_resp = MagicMock()
        agent_resp.text = '{"perspective": "no data", "proposed_action": "wait"}'
        agent_resp.input_tokens = 50
        agent_resp.output_tokens = 25
        chair_resp = MagicMock()
        chair_resp.text = '{"decision": "wait", "action_plan": "skip", "flag_for_jord": false, "flag_reason": ""}'
        chair_resp.input_tokens = 100
        chair_resp.output_tokens = 50
        executor_resp = MagicMock()
        executor_resp.tool_calls = []
        executor_resp.text = "Done."
        executor_resp.input_tokens = 80
        executor_resp.output_tokens = 30
        mock_llm.complete.side_effect = [agent_resp, agent_resp, chair_resp]
        mock_llm.complete_with_tools.return_value = executor_resp

        outcome = run_cycle(
            config=cycle_env["config"],
            repo=mock_repo,
            llm=mock_llm,
            memory_root=cycle_env["memory_root"],
            philosophy=cycle_env["philosophy"],
            repo_root=cycle_env["repo_root"],
        )
