"""Council deliberation: each agent gives their perspective, chair decides.

Flow:
1. Each agent gets: survey context + PHILOSOPHY.md + own identity + own memory + shared memory
2. Each responds with their perspective and proposed action
3. Chair agent receives all perspectives and commits to an action plan
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol, runtime_checkable

from brain.config import AgentConfig, Config
from brain.survey import SurveyResult

log = logging.getLogger("foreman.brain.council")


class LLMResponseLike(Protocol):
    """Minimal interface for LLM response objects."""

    text: str
    input_tokens: int
    output_tokens: int


class LLMPort(Protocol):
    """Interface for LLM calls — keeps council decoupled from provider."""

    def complete(
        self, model: str, system: str, message: str, max_tokens: Optional[int] = None
    ) -> LLMResponseLike: ...


@dataclass
class AgentPerspective:
    """One agent's response during deliberation."""

    agent_name: str
    perspective: str
    proposed_action: str


@dataclass
class CouncilResult:
    """Outcome of a council deliberation cycle."""

    perspectives: List[AgentPerspective]
    chair_name: str
    decision: str
    action_plan: str


def get_chair_index(journal_dir: Path) -> int:
    """Read the current chair index from journal. Returns 0 if not found."""
    index_file = journal_dir / ".chair_index"
    if not index_file.exists():
        return 0
    try:
        return int(index_file.read_text().strip())
    except (ValueError, OSError):
        return 0


def save_chair_index(journal_dir: Path, index: int) -> None:
    """Save the current chair index for next cycle's rotation."""
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / ".chair_index").write_text(str(index))


def _build_deliberation_prompt(
    agent: AgentConfig,
    philosophy: str,
    identity: str,
    own_memory_summary: str,
    shared_memory_summary: str,
    survey_context: str,
) -> tuple[str, str]:
    """Build system and user prompts for one agent's deliberation.

    Returns (system_prompt, user_message).
    """
    system = (
        f"{philosophy}\n\n"
        f"---\n\n"
        f"# Your Identity\n\n{identity}\n\n"
        f"You are {agent.name}, the {agent.role}. "
        f"You are participating in a council deliberation. "
        f"Review the current state and give your perspective on what the society "
        f"should prioritize. Propose a specific action.\n\n"
        f"Respond in this JSON format:\n"
        f'{{"perspective": "your analysis", "proposed_action": "specific action to take"}}'
    )
    user = (
        f"{survey_context}\n\n"
        f"---\n\n"
        f"# Your Private Memory\n\n{own_memory_summary}\n\n"
        f"# Shared Memory\n\n{shared_memory_summary}"
    )
    return system, user


def _build_chair_prompt(
    chair: AgentConfig,
    philosophy: str,
    identity: str,
    perspectives: List[AgentPerspective],
    survey_context: str,
) -> tuple[str, str]:
    """Build system and user prompts for the chair's decision.

    Returns (system_prompt, user_message).
    """
    perspectives_text = "\n\n".join(
        f"**{p.agent_name}**: {p.perspective}\n"
        f"Proposed action: {p.proposed_action}"
        for p in perspectives
    )
    system = (
        f"{philosophy}\n\n"
        f"---\n\n"
        f"# Your Identity\n\n{identity}\n\n"
        f"You are {chair.name}, the {chair.role}. "
        f"You are the chair for this council cycle. "
        f"Review all perspectives and decide on ONE action for this cycle. "
        f"Be specific about what to do and why.\n\n"
        f"If there is a disagreement about something risky (deleting code, "
        f"changing architecture), flag it for Jord instead of acting.\n\n"
        f"Respond in this JSON format:\n"
        f'{{"decision": "what we will do and why", '
        f'"action_plan": "specific steps to execute", '
        f'"flag_for_jord": false, '
        f'"flag_reason": ""}}'
    )
    user = (
        f"{survey_context}\n\n"
        f"---\n\n"
        f"# Council Perspectives\n\n{perspectives_text}"
    )
    return system, user


def _parse_json_response(text: str) -> dict:
    """Extract JSON from an LLM response, handling markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]  # skip opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)


def run_council(
    config: Config,
    agents: List[AgentConfig],
    survey: SurveyResult,
    philosophy: str,
    identity_texts: dict[str, str],
    memory_summaries: dict[str, str],
    shared_memory_summary: str,
    llm: LLMPort,
    journal_dir: Path,
) -> CouncilResult:
    """Run one council deliberation cycle.

    Args:
        config: Parsed config
        agents: Agent roster (ordered for chair rotation)
        survey: Current world state
        philosophy: PHILOSOPHY.md content
        identity_texts: {agent_name: identity file content}
        memory_summaries: {agent_name: summary of private memory}
        shared_memory_summary: Summary of shared memory
        llm: LLM client (protocol-typed)
        journal_dir: Path to memory/shared/journal/ for chair rotation state

    Returns:
        CouncilResult with perspectives and chair decision
    """
    survey_context = survey.to_context_string()

    # Phase 1: Deliberation — one call per agent
    perspectives: List[AgentPerspective] = []
    for agent in agents:
        identity = identity_texts.get(agent.name, f"You are {agent.name}.")
        own_memory = memory_summaries.get(agent.name, "(no private memory yet)")

        system, user = _build_deliberation_prompt(
            agent, philosophy, identity, own_memory,
            shared_memory_summary, survey_context,
        )
        try:
            response = llm.complete(
                model=config.model_council,
                system=system,
                message=user,
                max_tokens=1024,
            )
            data = _parse_json_response(response.text)
            perspectives.append(AgentPerspective(
                agent_name=agent.name,
                perspective=data.get("perspective", response.text),
                proposed_action=data.get("proposed_action", ""),
            ))
        except Exception as e:
            log.error(f"Agent {agent.name} deliberation failed: {e}")
            perspectives.append(AgentPerspective(
                agent_name=agent.name,
                perspective=f"(deliberation failed: {e})",
                proposed_action="",
            ))

    # Phase 2: Chair decision
    chair_index = get_chair_index(journal_dir)
    chair_index = chair_index % len(agents)
    chair = agents[chair_index]

    chair_identity = identity_texts.get(chair.name, f"You are {chair.name}.")
    system, user = _build_chair_prompt(
        chair, philosophy, chair_identity, perspectives, survey_context,
    )
    try:
        response = llm.complete(
            model=config.model_council,
            system=system,
            message=user,
            max_tokens=2048,
        )
        data = _parse_json_response(response.text)
        decision = data.get("decision", response.text)
        action_plan = data.get("action_plan", "")
    except Exception as e:
        log.error(f"Chair {chair.name} decision failed: {e}")
        decision = f"Chair decision failed: {e}"
        action_plan = ""

    # Rotate chair for next cycle
    next_index = (chair_index + 1) % len(agents)
    save_chair_index(journal_dir, next_index)

    return CouncilResult(
        perspectives=perspectives,
        chair_name=chair.name,
        decision=decision,
        action_plan=action_plan,
    )
