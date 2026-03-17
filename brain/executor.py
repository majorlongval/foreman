"""Execute council action plans using LLM tool-use calls.

Flow:
1. Build prompt from council decision + action plan
2. Call LLM with tool schemas
3. If LLM returns tool calls, execute each via execute_tool()
4. Feed results back to LLM
5. Repeat until LLM returns text-only or max rounds reached
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import List

from brain.council import CouncilResult
from brain.tools import TOOL_SCHEMAS, ToolContext, execute_tool
from brain.llm_client import estimate_cost

log = logging.getLogger("foreman.brain.executor")

# Max tool-use rounds per action to prevent runaway loops
DEFAULT_MAX_ROUNDS = 5


@dataclass
class ExecutionResult:
    """Result of executing a council action plan."""
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
    council_result: CouncilResult,
    llm: object,
    tool_ctx: ToolContext,
    model: str,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> ExecutionResult:
    """Execute the council's action plan via LLM tool-use loop.

    Args:
        council_result: The council's decision and action plan
        llm: LLM client with complete_with_tools() method
        tool_ctx: Context for tool execution (repo, memory, etc.)
        model: Model string for the execution LLM call
        max_rounds: Safety limit on tool-use rounds

    Returns:
        ExecutionResult with summary of what was done and total cost in USD
    """
    if not council_result.action_plan:
        return ExecutionResult(summary="No action plan — skipping execution.")

    tools = to_openai_tools(TOOL_SCHEMAS)
    system = (
        "You are the executor for an autonomous agent society. "
        "The council has deliberated and decided on an action. "
        "Use the available tools to carry out the action plan. "
        "Be precise and efficient — every tool call costs tokens.\n\n"
        "When you're done, respond with a brief summary of what you accomplished."
    )
    user = (
        f"## Council Decision\n{council_result.decision}\n\n"
        f"## Action Plan\n{council_result.action_plan}\n\n"
        "Execute this plan using the available tools."
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
                # LLM is done — return its final text
                summary = response.text or _summarize_actions(actions_taken)
                return ExecutionResult(summary=summary, cost_usd=total_cost)

            # Process each tool call
            # Append assistant message with tool calls to conversation
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

                # Feed result back as tool response
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        # Hit max rounds
        log.warning(f"Executor hit max rounds ({max_rounds})")
        summary = f"Reached max rounds ({max_rounds}). " + _summarize_actions(actions_taken)
        return ExecutionResult(summary=summary, cost_usd=total_cost)

    except Exception as e:
        log.error(f"Executor error: {e}")
        done = _summarize_actions(actions_taken)
        summary = f"Execution error: {e}" + (f"\nCompleted before error: {done}" if done else "")
        return ExecutionResult(summary=summary, cost_usd=total_cost)


def _summarize_actions(actions: List[str]) -> str:
    """Build a summary from the list of actions taken."""
    if not actions:
        return "No actions taken."
    return "Actions taken:\n" + "\n".join(f"  - {a}" for a in actions)
