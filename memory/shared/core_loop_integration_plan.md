# Specialized Agent Integration Strategy: Core Loop & Executor

## Overview
This document outlines the strategy for evolving the Fellowship from generalist LLMs into a set of specialized agents with distinct capabilities, tools, and domain-specific behaviors.

## Current State
- All agents use the same toolset (`TOOL_SCHEMAS`).
- Agents are distinguished primarily by their identity files (`agents/*.md`) and the roles assigned in `config.yml`.
- The `critic` role has hardcoded tool restrictions in `brain/tools.py` (e.g., `approve_pr`, `merge_pr`).

## Proposed Architecture Changes

### 1. Configuration (`brain/config.py`)
Update `AgentConfig` to include:
- `specialization`: A list of domain tags (e.g., `engineering`, `quality`, `orchestration`, `security`).
- `tool_groups`: A list of tool categories the agent is authorized to use.

### 2. Tool Categorization (`brain/tools.py`)
Organize `TOOL_SCHEMAS` into groups:
- **Core**: `read_file`, `list_files`, `read_memory`, `write_memory`, `check_budget`.
- **Engineering**: `create_issue`, `create_pr`, `push_to_pr`, `update_issue`.
- **Critic**: `approve_pr`, `merge_pr`, `close_issue`, `close_pr`, `post_comment`.
- **Communication**: `send_telegram`, `post_issue_comment`.

### 3. Execution Logic (`brain/executor.py`)
- **Dynamic Tool Filtering**: Modify `execute_action` to only provide the LLM with tools from its allowed `tool_groups`.
- **Specialized System Prompts**: Inject domain-specific instructions based on the agent's `specialization`. For example, Gimli (Engineering) should be prompted to focus on code quality and robustness, while Galadriel (Quality) focuses on test coverage and philosophy compliance.
- **Improved Task Mapping**: Ensure the `deliverable` requirement is explicitly linked to the agent's specialized toolset.

### 4. Council/Loop Integration (`brain/loop.py` & `brain/council.py`)
- **Capability-Aware Orchestration**: Elrond (the orchestrator) must be fed the mapping of agents to their specializations and toolsets. This allows the council to assign tasks more effectively (e.g., "Gimli, create a PR to fix the bug; Galadriel, review the PR for quality").
- **Phase Dependencies**: Refine the phase-based execution to allow for specialized "reviewer" phases that automatically follow "developer" phases.

## Implementation Roadmap

### Phase 1: Tool Grouping & Agent Configuration
1. Define tool groups in `brain/tools.py`.
2. Update `config.yml` and `AgentConfig` in `brain/config.py` to reflect agent specializations.
3. Update `agents/*.md` to align identity with specialization.

### Phase 2: Dynamic Tool Injection
1. Update `brain/executor.py` to filter `TOOL_SCHEMAS` using the new `tool_groups` from `AgentConfig`.
2. Implement validation in `execute_tool` to enforce these restrictions at runtime.

### Phase 3: Orchestrator Refinement
1. Modify the `run_council` prompt in `brain/council.py` to explicitly consider agent specializations when building the `ActionPlan`.
2. Add a "Capability Matrix" to the council's system prompt.

## Safety & Governance
- **Hard Restrictions**: Critical actions (like merging to `main`) remain locked behind the `critic` role even if the tool is in an agent's `tool_groups`.
- **Observation**: All specialized tool calls are recorded in the shared journal for auditability by the critic and human overseers.
