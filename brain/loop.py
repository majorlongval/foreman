"""The Wiggum loop — one brain cycle.

Each invocation:
1. Load config, philosophy, memory
2. Check budget — exit early if exhausted
3. Survey the world (GitHub, memory, budget)
4. Run council deliberation
5. Execute the decided action via tools
6. Write memory (journal, costs, incidents)
7. Exit
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from brain.config import Config, load_config
from brain.cost_tracking import load_today_spend, append_cost_entry
from brain.council import CouncilResult, run_council
from brain.memory import MemoryStore
from brain.survey import SurveyResult, gather_survey
from brain.executor import execute_action
from brain.tools import ToolContext

log = logging.getLogger("foreman.brain.loop")


@dataclass
class CycleOutcome:
    """Result of one brain cycle."""

    status: str  # "success", "budget_exhausted", "error"
    decision: str
    action_result: str
    cost: float
    error: Optional[str]


def run_cycle(
    config: Config,
    repo: object,
    llm: object,
    memory_root: Path,
    philosophy: str,
    repo_root: Path,
) -> CycleOutcome:
    """Run one brain cycle. This is the Wiggum loop body."""

    costs_dir = memory_root / "shared" / "costs"
    costs_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Check budget
    spent = load_today_spend(costs_dir)
    if spent >= config.daily_limit_usd:
        log.warning("Budget exhausted — skipping cycle")
        _write_journal(memory_root, "Budget exhausted. Cycle skipped.")
        return CycleOutcome("budget_exhausted", "", "", 0.0, None)

    # Step 2: Survey
    try:
        survey = gather_survey(config, memory_root, repo)
    except Exception as e:
        log.error(f"Survey failed: {e}")
        _write_incident(memory_root, f"Survey failed: {e}")
        return CycleOutcome("error", "", "", 0.0, str(e))

    # Step 3: Load agent identities and memories
    identity_texts = {}
    memory_summaries = {}
    for agent in config.agents:
        identity_path = repo_root / agent.identity_path
        if identity_path.exists():
            identity_texts[agent.name] = identity_path.read_text()
        else:
            identity_texts[agent.name] = f"You are {agent.name}, the {agent.role}."

        store = MemoryStore(memory_root, agent.name)
        files = store.list_files(agent.name)
        if files:
            summaries = []
            for f in files[:5]:  # Limit to 5 most recent
                content = store.read(agent.name, f)
                if content:
                    summaries.append(f"## {f}\n{content}")
            memory_summaries[agent.name] = "\n\n".join(summaries)
        else:
            memory_summaries[agent.name] = "(no private memory yet)"

    # Shared memory summary
    shared_store = MemoryStore(memory_root, "shared")
    shared_parts = []
    for subdir in ["decisions", "journal", "incidents"]:
        files = shared_store.list_files("shared", subdirectory=subdir)
        for f in files[:3]:
            content = shared_store.read("shared", f"{subdir}/{f}")
            if content:
                shared_parts.append(f"## {subdir}/{f}\n{content}")
    shared_memory_summary = "\n\n".join(shared_parts) if shared_parts else "(no shared memory yet)"

    # Step 4: Council
    journal_dir = memory_root / "shared" / "journal"
    try:
        council_result = run_council(
            config=config,
            agents=config.agents,
            survey=survey,
            philosophy=philosophy,
            identity_texts=identity_texts,
            memory_summaries=memory_summaries,
            shared_memory_summary=shared_memory_summary,
            llm=llm,
            journal_dir=journal_dir,
        )
    except Exception as e:
        log.error(f"Council failed: {e}")
        _write_incident(memory_root, f"Council failed: {e}")
        return CycleOutcome("error", "", "", 0.0, str(e))

    # Step 5: Act — execute the action plan via tool-use LLM call
    tool_ctx = ToolContext(
        repo=repo,
        memory_root=memory_root,
        agent_name=council_result.chair_name,
        notify_fn=lambda msg: False,  # Telegram wired in main()
        costs_dir=costs_dir,
        budget_limit=config.daily_limit_usd,
    )
    action_result = execute_action(
        council_result, llm, tool_ctx, config.model_default,
    )
    log.info(f"Council decided: {council_result.decision}")

    # Step 6: Reflect
    journal_entry = (
        f"# Cycle {datetime.now(timezone.utc).isoformat()}\n\n"
        f"Chair: {council_result.chair_name}\n\n"
        f"## Perspectives\n"
        + "\n".join(
            f"- **{p.agent_name}**: {p.perspective}" for p in council_result.perspectives
        )
        + f"\n\n## Decision\n{council_result.decision}\n\n"
        f"## Action Plan\n{council_result.action_plan}\n"
    )
    _write_journal(memory_root, journal_entry)

    return CycleOutcome(
        status="success",
        decision=council_result.decision,
        action_result=action_result,
        cost=0.0,  # TODO: track actual LLM costs from council
        error=None,
    )



def _write_journal(memory_root: Path, content: str) -> None:
    """Write a journal entry to shared memory."""
    journal_dir = memory_root / "shared" / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    (journal_dir / f"{timestamp}.md").write_text(content)


def _write_incident(memory_root: Path, content: str) -> None:
    """Write an incident to shared memory."""
    incidents_dir = memory_root / "shared" / "incidents"
    incidents_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    (incidents_dir / f"{timestamp}.md").write_text(content)


def main() -> None:
    """CLI entry point — load config, connect to GitHub, run one cycle."""
    from github import Github
    from llm_client import LLMClient
    from telegram_notifier import notify

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

    repo_root = Path(".")
    config = load_config(repo_root / "config.yml")

    # Load philosophy
    philosophy_path = repo_root / "PHILOSOPHY.md"
    if philosophy_path.exists():
        philosophy = philosophy_path.read_text()
    else:
        log.warning("PHILOSOPHY.md not found — running without constitution")
        philosophy = ""

    # Connect to GitHub
    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
    repo_name = os.environ.get("FOREMAN_REPO")
    if not gh_token or not repo_name:
        log.error("GITHUB_TOKEN and FOREMAN_REPO must be set")
        return

    gh = Github(gh_token)
    repo = gh.get_repo(repo_name)

    # LLM client
    llm = LLMClient()

    # Memory root
    memory_root = repo_root / "memory"

    # Run one cycle
    outcome = run_cycle(config, repo, llm, memory_root, philosophy, repo_root)
    log.info(f"Cycle complete: {outcome.status}")
    if outcome.error:
        log.error(f"Error: {outcome.error}")
