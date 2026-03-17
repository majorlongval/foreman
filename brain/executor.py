"""Execute an agent's assigned task using LLM tool-use calls.

Flow:
1. Build prompt from council decision + this agent's specific task
2. Call LLM with tool schemas
3. If LLM returns tool calls, execute each via execute_tool()
4. Feed results back to LLM
5. Repeat until LLM returns text-only or max rounds reached
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List

from brain.tools import TOOL_SCHEMAS, ToolContext, execute_tool
from brain.llm_client import estimate_cost

log = logging.getLogger("foreman.brain.executor")

# Max tool-use rounds per agent to prevent runaway loops.
# Raised from 5 to 8 so agents have enough room to complete multi-step tasks with deliverables.
DEFAULT_MAX_ROUNDS = 8


@dataclass
class ExecutionResult:
    """Result of one agent executing their assigned task."""
    summary: str
    cost_usd: float = 0.0


def to_openai_tools(schemas: list[dict]) -> list[dict]:
    """Convert our tool schemas to OpenAI/LiteLLM tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in schemas
    ]


def execute_action(
    task: str,
    agent_name: str,
    decision: str,
    llm: object,
    tool_ctx: ToolContext,
    model: str,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    deliverable: str = "",
) -> ExecutionResult:
    """Execute one agent's assigned task via LLM tool-use loop.

    Args:
        task: The specific task assigned to this agent by the chair
        agent_name: Name of the agent executing (used in logs and prompt)
        decision: Overall council decision — gives context for why this task matters
        llm: LLM client with complete_with_tools() method
        tool_ctx: Context for tool execution (repo, memory, budget, etc.)
        model: Model string for the LLM call
        max_rounds: Safety limit on tool-use rounds per agent
        deliverable: Specific artifact this agent must produce (file, issue, PR, etc.)

    Returns:
        ExecutionResult with summary of what was done and total cost in USD
    """
    if not task:
        return ExecutionResult(summary="No task assigned — skipping execution.")

    tools = to_openai_tools(TOOL_SCHEMAS)
    system = (
        f"You are {agent_name}, an autonomous agent. "
        "The council has deliberated and assigned you a specific task. "
        "Use the available tools to carry it out. "
        "Be precise and efficient — every tool call costs tokens.\n\n"
        "When you're done, respond with a brief summary of what you accomplished."
    )

    # Build deliverable section — reminds the agent of the concrete output they owe
    # and instructs them to record their work in their own memory file so the next
    # cycle can see what was accomplished.
    deliverable_section = (
        f"\n\n## Required Deliverable\n"
        f"You MUST produce: {deliverable}\n\n"
        f"After completing your task, use write_memory to save a brief note about "
        f"what you did to memory/{agent_name}/cycle_notes.md."
        if deliverable else ""
    )

    user = (
        f"## Council Decision\n{decision}\n\n"
        f"## Your Task\n{task}"
        + deliverable_section
        + "\n\nExecute your task using the available tools."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    actions_taken: List[str] = []
    total_cost = 0.0

    try:
        for round_num in range(max_rounds):
            response = llm.complete_with_tools(
                model=model,
                messages=messages,
                tools=tools,
                max_tokens=2048,
            )
            total_cost += estimate_cost(model, response.input_tokens, response.output_tokens)

            if not response.tool_calls:
                summary = response.text or _summarize_actions(actions_taken)
                return ExecutionResult(summary=summary, cost_usd=total_cost)

            # Append assistant message with tool calls, then feed each result back
            messages.append(response.raw_message)

            for tool_call in response.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                log.info(f"Tool call: {name}({args})")
                result = execute_tool(name, args, tool_ctx)
                actions_taken.append(f"{name}: {result[:100]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        log.warning(f"Executor hit max rounds ({max_rounds}) for {agent_name}")
        summary = f"Reached max rounds ({max_rounds}). " + _summarize_actions(actions_taken)
        return ExecutionResult(summary=summary, cost_usd=total_cost)

    except Exception as e:
        log.error(f"Executor error for {agent_name}: {e}")
        done = _summarize_actions(actions_taken)
        summary = f"Execution error: {e}" + (f"\nCompleted before error: {done}" if done else "")
        return ExecutionResult(summary=summary, cost_usd=total_cost)


def _summarize_actions(actions: List[str]) -> str:
    """Build a summary from the list of actions taken."""
    if not actions:
        return "No actions taken."
    return "Actions taken:\n" + "\n".join(f"  - {a}" for a in actions)
