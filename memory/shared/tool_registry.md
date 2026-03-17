# Registered Society Tools

| Tool Name | Class Path | Registered Status |
|-----------|------------|-------------------|
| DefaultToolExecutor | lib/foreman/core/executor.py | Registered |
| MockTool | tests/core/test_tool_executor.py | Testing Only |
| read_pr | internal | Registered |
| post_comment | internal | Registered |
| create_pr | internal | Registered |
| approve_pr | internal | Registered |
| write_memory | internal | Registered |
| read_memory | internal | Registered |

Tools are registered within the `DefaultToolExecutor` at runtime to ensure type safety and cost auditing.
