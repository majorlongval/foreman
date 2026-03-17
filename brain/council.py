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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from pydantic import BaseModel

from brain.config import AgentConfig, Config
from brain.survey import SurveyResult
from brain.llm_client import estimate_cost

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
Review all perspectives and synthesize them into a decision. \
Then assign a specific, concrete task to EACH agent by name. \
Every agent should have work to do — parallel action is faster than sequential.

If there is a disagreement about something risky (deleting code, \
changing architecture), flag it for Jord instead of acting.

The agents in this council are: {agent_names}

CRITICAL: The "assignments" field is REQUIRED and must contain a task for EVERY agent. \
If an agent has no specific task, assign them a review or documentation task. \
Never leave "assignments" empty.

You MUST respond with ONLY a JSON object, no other text:
{{"decision": "what we will do and why", \
"action_plan": "overall summary of the plan", \
"assignments": {{{assignment_example}}}, \
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
    assignments: Dict[str, str] = {}  # agent_name → specific task for this cycle
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
        self, model: str, system: str, message: str, max_tokens: Optional[int] = None,
        response_format: Optional[type] = None,
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
    assignments: Dict[str, str] = field(default_factory=dict)  # agent_name → task


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
                max_tokens=2048,
                response_format=AgentResponse,
            )
            total_cost += estimate_cost(
                config.model_council, response.input_tokens, response.output_tokens
            )
            parsed = parse_agent_response(response.text)
            log.info(f"[{agent.name}] {parsed.perspective} → {parsed.proposed_action}")
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
        chair, philosophy, chair_identity, perspectives, survey_context, agents,
    )
    try:
        response = llm.complete(
            model=config.model_council,
            system=system,
            message=user,
            max_tokens=4096,  # Chair needs more tokens: decision + action_plan + assignments for all agents
            response_format=ChairResponse,
        )
        total_cost += estimate_cost(
            config.model_council, response.input_tokens, response.output_tokens
        )
        parsed = parse_chair_response(response.text)
        decision = parsed.decision
        action_plan = parsed.action_plan
        assignments = parsed.assignments
        log.info(f"[{chair.name} / chair] Decision: {decision}")

        # Validate assignments — if chair didn't assign tasks, fall back
        expected_names = {a.name for a in agents}
        if not assignments:
            log.warning(
                f"Chair returned empty assignments — falling back to "
                f"action_plan for all agents. Raw response: {response.text[:500]}"
            )
            assignments = {a.name: action_plan for a in agents}
        else:
            missing = expected_names - set(assignments.keys())
            if missing:
                log.warning(f"Chair missed assignments for: {missing}")
                for name in missing:
                    assignments[name] = action_plan

        for agent_name, task in assignments.items():
            log.info(f"  → {agent_name}: {task}")
        if parsed.flag_for_jord:
            log.warning(f"[{chair.name} / chair] Flagged for Jord: {parsed.flag_reason}")
    except Exception as e:
        log.error(f"Chair {chair.name} decision failed: {e}")
        decision = f"Chair decision failed: {e}"
        action_plan = ""
        assignments = {}

    # Rotate chair for next cycle
    next_index = (chair_index + 1) % len(agents)
    save_chair_index(journal_dir, next_index)

    return CouncilResult(
        perspectives=perspectives,
        chair_name=chair.name,
        decision=decision,
        action_plan=action_plan,
        cost_usd=total_cost,
        assignments=assignments,
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
    all_agents: List[AgentConfig],
) -> tuple[str, str]:
    """Build system and user prompts for the chair's decision."""
    perspectives_text = "\n\n".join(
        f"**{p.agent_name}**: {p.perspective}\n"
        f"Proposed action: {p.proposed_action}"
        for p in perspectives
    )
    agent_names = ", ".join(a.name for a in all_agents)
    # Build example assignments so the LLM knows the exact format expected
    assignment_example = ", ".join(
        f'"{a.name}": "task for {a.name}"' for a in all_agents
    )
    system = CHAIR_SYSTEM.format(
        philosophy=philosophy,
        identity=identity,
        chair_name=chair.name,
        chair_role=chair.role,
        agent_names=agent_names,
        assignment_example=assignment_example,
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


def _fix_json(text: str) -> str:
    """Fix common JSON issues produced by LLMs (trailing commas, Python literals)."""
    # Remove trailing commas before closing brackets/braces
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # Replace Python-style literals with JSON equivalents (outside strings is best-effort)
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)
    return text


def parse_json_response(text: str) -> dict:
    """Extract and parse JSON from an LLM response."""
    extracted = extract_json(text)
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        return json.loads(_fix_json(extracted))


def parse_agent_response(text: str) -> AgentResponse:
    """Parse an agent's deliberation response with pydantic validation."""
    return AgentResponse.model_validate(parse_json_response(text))


def parse_chair_response(text: str) -> ChairResponse:
    """Parse the chair's decision response with pydantic validation."""
    return ChairResponse.model_validate(parse_json_response(text))
