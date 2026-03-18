"""Elrond orchestration: one LLM call assigns tasks to all worker agents.

Flow:
1. Elrond receives the full world state: survey + all agent memories + shared memory
2. Elrond returns a structured decision with ordered phases, one task per agent
3. No deliberation round — Elrond is the sole decision maker for task assignment

This replaces the old council model (N deliberation calls + 1 rotating chair call)
with a single orchestration call, cutting per-cycle LLM cost by ~80%.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Protocol

from pydantic import BaseModel

from brain.config import AgentConfig, Config
from brain.llm_client import estimate_cost
from brain.survey import SurveyResult

log = logging.getLogger("foreman.brain.council")


# ── Prompt templates ──────────────────────────────────────────

# Elrond's identity and lane knowledge. This is the system prompt that shapes
# how he thinks about the board — he knows each agent's lane and must not
# assign cross-lane work.
ELROND_SYSTEM = """You are Elrond, the orchestrator of a multi-agent software development society.

You do not build, review, or research yourself. You read the board and move pieces.
Your job: assign exactly one concrete, deliverable task to each worker agent per cycle.

## The Worker Agents

- **gandalf** (scout): creates GitHub issues (new feature/bug found/gap spotted) OR writes a \
research doc to memory/shared/. His deliverable is always a file written or an issue created.
- **gimli** (builder): opens one PR with working code, OR pushes meaningful commits to an existing \
branch. His deliverable is a PR or a commit.
- **galadriel** (critic): reviews one open PR using read_pr + post_comment with findings, \
then approves via approve_pr if the code is good. Her deliverable is a PR review posted.
- **samwise** (gardener): one concrete maintenance action — address review feedback on a PR, \
close a stale issue, or triage the backlog. His deliverable is a specific issue or PR acted on.

## Assignment Rules

- Assign ONE concrete task per agent based on the current world state.
- Use phases to sequence dependencies: phase 1 runs first (independent), \
phase 2+ runs after phase 1 completes. Within-cycle phases are for rare true dependencies \
(e.g. gimli opens a PR in phase 1, galadriel reviews it in phase 2 of the NEXT cycle — \
don't sequence within a cycle unless gimli's PR is already open and galadriel must review it NOW).
- Every task MUST specify a concrete deliverable: a specific file written, issue created, \
PR opened, or comment posted. Vague deliverables are not acceptable.
- If something is risky (deleting architecture, reverting large changes), flag it for Jord \
instead of acting.
- Agents should write a note about their work to memory/{{agent_name}}/cycle_notes.md.

The assignable worker agents are: {worker_agent_names}

CRITICAL: The "phases" field is REQUIRED and must contain at least one phase with tasks for \
ALL worker agents. Never leave "phases" empty.

You MUST respond with ONLY a JSON object, no other text:
{{"decision": "what we will do and why", \
"action_plan": "overall summary of the plan", \
"phases": [{phase_example}], \
"flag_for_jord": false, \
"flag_reason": ""}}"""

# User prompt carries the world state: survey context + per-agent memory + shared memory.
# All agent memories are included so Elrond has full situational awareness.
ELROND_USER = """{survey_context}

---

# Agent Memories

{agent_memories_text}

# Shared Memory

{shared_memory}"""


# ── Pydantic response models ─────────────────────────────────


class AgentResponse(BaseModel):
    """Expected JSON from an agent's deliberation call (kept for backwards compatibility)."""

    perspective: str
    proposed_action: str


class AgentAssignment(BaseModel):
    """One agent's assignment within a phase."""

    agent: str  # agent name matching config
    task: str  # specific work to do this cycle
    deliverable: str  # concrete artifact: file written, issue created, PR opened, etc.


class ChairResponse(BaseModel):
    """Expected JSON from Elrond's orchestration call.

    phases is a list of phases, each phase is a list of assignments.
    Phases execute in order; assignments within a phase run independently.
    """

    decision: str
    action_plan: str
    phases: List[List[AgentAssignment]] = []
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
        self,
        model: str,
        system: str,
        message: str,
        max_tokens: Optional[int] = None,
        response_format: Optional[type] = None,
    ) -> LLMResponseLike: ...


# ── Domain types ──────────────────────────────────────────────


@dataclass
class AgentPerspective:
    """One agent's response during deliberation (kept for backwards compatibility — no longer used)."""

    agent_name: str
    perspective: str
    proposed_action: str


@dataclass
class CouncilResult:
    """Outcome of one Elrond orchestration cycle."""

    # perspectives is always [] — deliberation is gone, kept for interface stability
    perspectives: List[AgentPerspective]
    chair_name: str  # always "elrond"
    decision: str
    action_plan: str
    cost_usd: float = 0.0
    # Ordered phases of execution; each phase is a list of assignments that run independently.
    # Phase N+1 starts only after phase N finishes (enabling agents to depend on prior output).
    phases: List[List[AgentAssignment]] = field(default_factory=list)


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
    """Run one Elrond orchestration cycle — a single LLM call assigns tasks to all workers."""
    survey_context = survey.to_context_string()

    # Worker agents are all agents except Elrond himself (role=orchestrator).
    # We exclude the orchestrator from the assignable list so he never self-assigns.
    worker_agents = [a for a in agents if a.role != "orchestrator"]

    system, user = build_elrond_prompt(
        worker_agents=worker_agents,
        survey_context=survey_context,
        memory_summaries=memory_summaries,
        shared_memory_summary=shared_memory_summary,
    )

    try:
        response = llm.complete(
            model=config.model_elrond,
            system=system,
            message=user,
            response_format=ChairResponse,
        )
        cost = estimate_cost(config.model_elrond, response.input_tokens, response.output_tokens)
        parsed = parse_chair_response(response.text)
        decision = parsed.decision
        action_plan = parsed.action_plan
        phases = parsed.phases
        log.info(f"[elrond] Decision: {decision}")
        for phase_idx, phase in enumerate(phases):
            for assignment in phase:
                log.info(
                    f"  → phase {phase_idx + 1} [{assignment.agent}]: {assignment.task} "
                    f"(deliverable: {assignment.deliverable})"
                )
        if parsed.flag_for_jord:
            log.warning(f"[elrond] Flagged for Jord: {parsed.flag_reason}")
    except Exception as e:
        log.error(f"Elrond orchestration failed: {e}")
        decision = f"Elrond orchestration failed: {e}"
        action_plan = ""
        phases = []
        cost = 0.0

    return CouncilResult(
        perspectives=[],  # deliberation is gone; field kept for interface stability
        chair_name="elrond",
        decision=decision,
        action_plan=action_plan,
        cost_usd=cost,
        phases=phases,
    )


# ── Prompt builder ────────────────────────────────────────────


def build_elrond_prompt(
    worker_agents: List[AgentConfig],
    survey_context: str,
    memory_summaries: dict[str, str],
    shared_memory_summary: str,
) -> tuple[str, str]:
    """Build Elrond's system and user prompts.

    System: who Elrond is + each agent's lane + JSON format requirement.
    User: world state — survey + all agent memories + shared memory.
    """
    worker_names = ", ".join(a.name for a in worker_agents)

    # Concrete phases example so the LLM knows the exact JSON shape to return.
    # Two phases if >2 agents (to illustrate sequencing), one phase otherwise.
    if len(worker_agents) <= 2:
        phase1 = ", ".join(
            f'{{"agent": "{a.name}", "task": "task for {a.name}", "deliverable": "memory/{a.name}/cycle_notes.md"}}'
            for a in worker_agents
        )
        phase_example = f"[{phase1}]"
    else:
        mid = len(worker_agents) // 2
        phase1 = ", ".join(
            f'{{"agent": "{a.name}", "task": "task for {a.name}", "deliverable": "memory/{a.name}/cycle_notes.md"}}'
            for a in worker_agents[:mid]
        )
        phase2 = ", ".join(
            f'{{"agent": "{a.name}", "task": "task for {a.name}", "deliverable": "memory/{a.name}/cycle_notes.md"}}'
            for a in worker_agents[mid:]
        )
        phase_example = f"[{phase1}], [{phase2}]"

    system = ELROND_SYSTEM.format(
        worker_agent_names=worker_names,
        phase_example=phase_example,
    )

    # Include each agent's private memory keyed by name so Elrond can see
    # what each agent has been doing and what they planned last cycle.
    agent_memories_parts = []
    for agent in worker_agents:
        summary = memory_summaries.get(agent.name, "(no private memory yet)")
        agent_memories_parts.append(f"## {agent.name} ({agent.role})\n{summary}")
    agent_memories_text = "\n\n".join(agent_memories_parts)

    user = ELROND_USER.format(
        survey_context=survey_context,
        agent_memories_text=agent_memories_text,
        shared_memory=shared_memory_summary,
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
        return stripped[first : last + 1]

    return stripped


def _fix_json(text: str) -> str:
    """Fix common JSON issues produced by LLMs (trailing commas, Python literals, unquoted keys)."""
    # Remove trailing commas before closing brackets/braces
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # Replace Python-style literals with JSON equivalents (outside strings is best-effort)
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)
    # Quote unquoted object keys: match word chars not preceded by " and followed by whitespace+colon
    text = re.sub(r'(?<!["\w])(\b[a-zA-Z_][a-zA-Z0-9_]*\b)(?=\s*:)', r'"\1"', text)
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
    """Parse Elrond's orchestration response with pydantic validation."""
    return ChairResponse.model_validate(parse_json_response(text))
