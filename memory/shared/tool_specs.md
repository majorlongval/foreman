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
