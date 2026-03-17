"""Council deliberation: each agent gives their perspective, chair decides.

Flow:
1. Each agent gets: survey context + PHILOSOPHY.md + own identity + own memory + shared memory
2. Each responds with their perspective and proposed action
3. Chair agent receives all perspectives and commits to an action plan
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol

from pydantic import BaseModel

from brain.config import AgentConfig, Config
from brain.survey import SurveyResult
from llm_client import estimate_cost

log = logging.getLogger("foreman.brain.council")


# ── Prompt templates ──────────────────────────────────────────

DELIBERATION_SYSTEM = """{philosophy}

---

# Your Identity

{identity}

You are {agent_name}, the {agent_role}. \
You are participating in a council deliberation. \
Review the current state and give your perspective on what the society \
should prioritize. Propose a specific action.

You MUST respond with ONLY a JSON object, no other text:
{{"perspective": "your analysis", "proposed_action": "specific action to take"}}"""

DELIBERATION_USER = """{survey_context}

---

# Your Private Memory

{own_memory}

# Shared Memory

{shared_memory}"""

CHAIR_SYSTEM = """{philosophy}

---

# Your Identity

{identity}

You are {chair_name}, the {chair_role}. \
You are the chair for this council cycle. \
Review all perspectives and decide on ONE action for this cycle. \
Be specific about what to do and why.

If there is a disagreement about something risky (deleting code, \
changing architecture), flag it for Jord instead of acting.

You MUST respond with ONLY a JSON object, no other text:
{{"decision": "what we will do and why", \
"action_plan": "specific steps to execute", \
"flag_for_jord": false, \
"flag_reason": ""}}"""

CHAIR_USER = """{survey_context}

---

# Council Perspectives

{perspectives_text}"""


# ── Pydantic response models ─────────────────────────────────

class AgentResponse(BaseModel):
    """Expected JSON from an agent's deliberation call."""
    perspective: str
    proposed_action: str


class ChairResponse(BaseModel):
    """Expected JSON from the chair's decision call."""
    decision: str
    action_plan: str
    flag_for_jord: bool = False
    flag_reason: str = ""


# ── Protocols ─────────────────────────────────────────────────

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


# ── Domain types ──────────────────────────────────────────────

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
    cost_usd: float = 0.0


# ── Main entry point ──────────────────────────────────────────

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
    """Run one council deliberation cycle."""
    survey_context = survey.to_context_string()

    # Phase 1: Deliberation — one call per agent
    perspectives: List[AgentPerspective] = []
    total_cost = 0.0
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
            total_cost += estimate_cost(
                config.model_council, response.input_tokens, response.output_tokens
            )
            parsed = parse_agent_response(response.text)
            perspectives.append(AgentPerspective(
                agent_name=agent.name,
                perspective=parsed.perspective,
                proposed_action=parsed.proposed_action,
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
        total_cost += estimate_cost(
            config.model_council, response.input_tokens, response.output_tokens
        )
        parsed = parse_chair_response(response.text)
        decision = parsed.decision
        action_plan = parsed.action_plan
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
        cost_usd=total_cost,
    )


# ── Chair rotation ────────────────────────────────────────────

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


# ── Prompt builders ───────────────────────────────────────────

def _build_deliberation_prompt(
    agent: AgentConfig,
    philosophy: str,
    identity: str,
    own_memory_summary: str,
    shared_memory_summary: str,
    survey_context: str,
) -> tuple[str, str]:
    """Build system and user prompts for one agent's deliberation."""
    system = DELIBERATION_SYSTEM.format(
        philosophy=philosophy,
        identity=identity,
        agent_name=agent.name,
        agent_role=agent.role,
    )
    user = DELIBERATION_USER.format(
        survey_context=survey_context,
        own_memory=own_memory_summary,
        shared_memory=shared_memory_summary,
    )
    return system, user


def _build_chair_prompt(
    chair: AgentConfig,
    philosophy: str,
    identity: str,
    perspectives: List[AgentPerspective],
    survey_context: str,
) -> tuple[str, str]:
    """Build system and user prompts for the chair's decision."""
    perspectives_text = "\n\n".join(
        f"**{p.agent_name}**: {p.perspective}\n"
        f"Proposed action: {p.proposed_action}"
        for p in perspectives
    )
    system = CHAIR_SYSTEM.format(
        philosophy=philosophy,
        identity=identity,
        chair_name=chair.name,
        chair_role=chair.role,
    )
    user = CHAIR_USER.format(
        survey_context=survey_context,
        perspectives_text=perspectives_text,
    )
    return system, user


# ── Response parsing ──────────────────────────────────────────

def extract_json(text: str) -> str:
    """Extract a JSON object string from LLM output.

    Handles: plain JSON, markdown fences, and text surrounding JSON.
    """
    stripped = text.strip()

    # Try markdown fenced blocks first
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # Find first { to last } — handles preamble text
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last > first:
        return stripped[first:last + 1]

    return stripped


def parse_json_response(text: str) -> dict:
    """Extract and parse JSON from an LLM response."""
    return json.loads(extract_json(text))


def parse_agent_response(text: str) -> AgentResponse:
    """Parse an agent's deliberation response with pydantic validation."""
    return AgentResponse.model_validate(parse_json_response(text))


def parse_chair_response(text: str) -> ChairResponse:
    """Parse the chair's decision response with pydantic validation."""
    return ChairResponse.model_validate(parse_json_response(text))
