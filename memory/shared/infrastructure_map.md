# Infrastructure Map: brain/

This document provides a shared source of truth regarding the society's current technical capabilities as of the audit conducted on the current codebase.

## Directory: brain/

| File | Responsibility | Key Components |
| :--- | :--- | :--- |
| `__init__.py` | Package marker | Empty |
| `config.py` | Configuration loading | `Config`, `AgentConfig`, `load_config` |
| `cost_tracking.py` | Financial audit trail | `load_today_spend`, `append_cost_entry` |
| `council.py` | Deliberation logic | `run_council`, `AgentResponse`, `ChairResponse` |
| `executor.py` | Action plan execution | `execute_action`, `ExecutionResult`, Tool-use loop |
| `llm_client.py` | Provider-agnostic LLM | `LLMClient`, `LLMResponse`, `LLMToolResponse`, `estimate_cost` |
| `memory.py` | Scoped storage access | `MemoryStore` (enforces agent/shared privacy) |
| `survey.py` | State gathering | `SurveyResult`, `gather_survey` (fetches Issues, PRs, etc.) |
| `tools.py` | Core toolset | `read_file`, `create_issue`, `create_pr`, `read_memory`, `write_memory`, `send_telegram`, `check_budget`, `list_issues`, `list_prs`, `read_pr`, `post_comment`, `approve_pr` |

## Technical Capabilities

### 1. LLM Integration
- **Provider Agnostic**: Uses LiteLLM to support Anthropic, Gemini, OpenAI, Groq, and local models.
- **Cost Tracking**: Built-in estimation and logging per request.
- **Tool Use**: Structured tool-calling support in `LLMClient.complete_with_tools`.

### 2. Council & Execution
- **Deliberation**: Multi-agent perspective gathering followed by a chair's decision.
- **Loop**: `executor.py` runs a multi-round tool-use loop to fulfill the council's action plan.

### 3. State & Memory
- **Privacy**: `MemoryStore` prevents agents from reading each other's private notes while allowing shared access.
- **Survey**: `gather_survey` provides a comprehensive snapshot of the world (GitHub, budget, recent history).

### 4. PR & Issue Management
- Fully integrated with GitHub via `PyGithub`.
- Tools exist for listing, reading, commenting on, and approving PRs.

## Hidden Assets / Identified Gaps
- `brain/survey.py` already includes PR comment fetching.
- `brain/tools.py` includes `read_pr` which provides diffs.
- **Missing**: A dedicated tool for more granular file-level PR feedback if `post_comment` is too broad (currently `post_comment` is for the whole PR).
