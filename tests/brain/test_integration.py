"""Integration test — full brain cycle with mocks."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from brain.config import AgentConfig, Config
from brain.loop import run_cycle


@pytest.fixture
def full_env(tmp_path: Path):
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

    # Mock LLM — Elrond makes exactly 1 call (no deliberation round anymore)
    elrond_resp = MagicMock()
    elrond_resp.text = (
        '{"decision": "Research models", "action_plan": "List available models",'
        '"phases": [[{"agent": "gandalf", "task": "scout available models", "deliverable": "memory/gandalf/cycle_notes.md"},'  # noqa: E501
        '{"agent": "gimli", "task": "log findings", "deliverable": "memory/gimli/cycle_notes.md"}]],'
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

    return {
        "config": config,
        "repo_root": repo_root,
        "memory_root": memory_root,
        "mock_repo": mock_repo,
        "mock_llm": mock_llm,
    }


class TestFullCycle:
    def test_complete_cycle_produces_journal_entry(self, full_env) -> None:
        outcome = run_cycle(
            config=full_env["config"],
            repo=full_env["mock_repo"],
            llm=full_env["mock_llm"],
            memory_root=full_env["memory_root"],
            philosophy="Be good. Grow.",
            repo_root=full_env["repo_root"],
        )
        assert outcome.status == "success"
        assert outcome.error is None

        # Verify journal was written
        journal_dir = full_env["memory_root"] / "shared" / "journal"
        journal_files = [f for f in journal_dir.iterdir() if f.suffix == ".md"]
        assert len(journal_files) >= 1

        # Verify journal content mentions the decision
        content = journal_files[0].read_text()
        assert "Research models" in content

    def test_budget_exhausted_skips_everything(self, full_env) -> None:
        # Spend all the budget
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        costs_dir = full_env["memory_root"] / "shared" / "costs"
        (costs_dir / f"{today}.jsonl").write_text(json.dumps({"cost_usd": 10.0}) + "\n")
        outcome = run_cycle(
            config=full_env["config"],
            repo=full_env["mock_repo"],
            llm=full_env["mock_llm"],
            memory_root=full_env["memory_root"],
            philosophy="Be good.",
            repo_root=full_env["repo_root"],
        )
        assert outcome.status == "budget_exhausted"
        full_env["mock_llm"].complete.assert_not_called()
