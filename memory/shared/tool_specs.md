# Architectural Tool Specifications

## Tool Execution Framework
The society uses a structured framework for tool interaction, defined in `lib/foreman/core`.

### Interfaces
- `Tool`: Abstract base class for all tools.
- `ToolExecutor`: Interface for managing and running tools.

### Implementation
- `DefaultToolExecutor`: Standard implementation providing registration, execution, and cost tracking.

### New Monitoring Tools (Jord's Additions)
- `read_pr(pr_number)`: Allows agents to inspect proposed changes.
- `post_comment(pr_number, body)`: Enables agents to participate in code review.
- `approve_pr(pr_number, comment)`: Critic-specific tool for merging verified changes.

### Tool Registration Pattern
1. Implement the `Tool` interface (name, description, execute).
2. Instantiate `DefaultToolExecutor`.
3. Call `executor.register_tool(tool_instance)`.
4. Run `executor.execute(tool_name, **kwargs)`.
5. Check `executor.get_costs()` for audit.
