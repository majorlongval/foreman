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
    notify_fn: object = None,
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
        survey = gather_survey(config, memory_root, repo, repo_root=repo_root)
    except Exception as e:
        log.error(f"Survey failed: {e}")
        _write_incident(memory_root, f"Survey failed: {e}", notify_fn)
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

    # Shared memory summary — scan ALL subdirectories under memory/shared/, not just fixed ones.
    # This lets agents add new shared memory categories (e.g. "plans", "notes") without needing
    # code changes here. We collect up to 10 most-recent files across all subdirs + root .md files.
    shared_root = memory_root / "shared"
    shared_parts = []
    if shared_root.exists():
        # Gather all .md files from every subdir + root-level files, sorted newest first
        all_shared_files: list[tuple] = []
        for item in shared_root.iterdir():
            if item.is_dir():
                for f in item.glob("*.md"):
                    all_shared_files.append((f.stat().st_mtime, f, item.name))
            elif item.suffix == ".md":
                all_shared_files.append((item.stat().st_mtime, item, ""))
        all_shared_files.sort(reverse=True)  # most-recent first
        for _, file_path, subdir in all_shared_files[:10]:
            rel = f"{subdir}/{file_path.name}" if subdir else file_path.name
            content = file_path.read_text()
            if content.strip():
                shared_parts.append(f"## {rel}\n{content}")
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
        _write_incident(memory_root, f"Council failed: {e}", notify_fn)
        return CycleOutcome("error", "", "", 0.0, str(e))

    log.info(f"Council decided: {council_result.decision}")

    # Step 5: Execute phases in order. Within each phase, assignments run sequentially
    # (sequential calls, but conceptually independent — order within a phase doesn't matter).
    # Phase N+1 only starts after phase N completes, so later phases can depend on earlier output.
    execution_summaries = []
    total_execution_cost = 0.0
    for phase_idx, phase in enumerate(council_result.phases):
        log.info(f"Executing phase {phase_idx + 1} ({len(phase)} assignment(s))")
        for assignment in phase:
            agent_cfg = next((a for a in config.agents if a.name == assignment.agent), None)
            if not agent_cfg:
                # Chair assigned a name that doesn't exist in config — skip gracefully
                log.warning(f"Unknown agent in assignment: {assignment.agent} — skipping")
                continue
            agent_tool_ctx = ToolContext(
                repo=repo,
                memory_root=memory_root,
                agent_name=agent_cfg.name,
                agent_role=agent_cfg.role,
                notify_fn=notify_fn or (lambda msg: False),
                costs_dir=costs_dir,
                budget_limit=config.daily_limit_usd,
            )
            result = execute_action(
                task=assignment.task,
                deliverable=assignment.deliverable,
                agent_name=assignment.agent,
                decision=council_result.decision,
                llm=llm,
                tool_ctx=agent_tool_ctx,
                model=config.model_default,
            )
            execution_summaries.append(f"[{assignment.agent}] {result.summary}")
            total_execution_cost += result.cost_usd
            append_cost_entry(
                costs_dir,
                agent=assignment.agent,
                model=config.model_default,
                action="execution",
                input_tokens=0,
                output_tokens=0,
                cost_usd=result.cost_usd,
            )

    # Step 6: Persist council cost
    append_cost_entry(
        costs_dir,
        agent=council_result.chair_name,
        model=config.model_council,
        action="council",
        input_tokens=0,   # tokens already summed into cost_usd by run_council
        output_tokens=0,
        cost_usd=council_result.cost_usd,
    )

    total_cost = council_result.cost_usd + total_execution_cost

    # Step 7: Reflect — no Perspectives section because Elrond replaced deliberation
    journal_entry = (
        f"# Cycle {datetime.now(timezone.utc).isoformat()}\n\n"
        f"Orchestrator: {council_result.chair_name}\n\n"
        f"## Decision\n{council_result.decision}\n\n"
        f"## Action Plan\n{council_result.action_plan}\n\n"
        f"## Cost\n${total_cost:.4f}\n"
    )
    _write_journal(memory_root, journal_entry)

    # Clear inbox now that agents have read it this cycle
    inbox_path = repo_root / "INBOX.md"
    if inbox_path.exists():
        inbox_path.write_text("")

    # Deliver outbox to Jord via Telegram, then clear it
    outbox_path = repo_root / "OUTBOX.md"
    if outbox_path.exists():
        message = outbox_path.read_text().strip()
        if message and notify_fn:
            notify_fn(f"📬 Message from the council:\n\n{message}")
        outbox_path.write_text("")

    return CycleOutcome(
        status="success",
        decision=council_result.decision,
        action_result="\n".join(execution_summaries) if execution_summaries else "No agents had tasks.",
        cost=total_cost,
        error=None,
    )



def _write_journal(memory_root: Path, content: str) -> None:
    """Write a journal entry to shared memory."""
    journal_dir = memory_root / "shared" / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    (journal_dir / f"{timestamp}.md").write_text(content)


def _write_incident(memory_root: Path, content: str, notify_fn: object = None) -> None:
    """Write an incident to shared memory and alert Jord via Telegram."""
    incidents_dir = memory_root / "shared" / "incidents"
    incidents_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    (incidents_dir / f"{timestamp}.md").write_text(content)
    if notify_fn:
        notify_fn(f"⚠️ Foreman incident:\n\n{content}")


def main() -> None:
    """CLI entry point — load config, connect to GitHub, run one cycle."""
    from github import Github
    from brain.llm_client import LLMClient
    from brain.telegram_notifier import notify

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
    outcome = run_cycle(config, repo, llm, memory_root, philosophy, repo_root, notify_fn=notify)
    log.info(f"Cycle complete: {outcome.status}")
    if outcome.error:
        log.error(f"Error: {outcome.error}")
