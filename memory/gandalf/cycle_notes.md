# Gandalf Cycle Notes - 2026-03-24

## Task: Create GitHub issues for Core Loop Integration (#130)

Following the research in `memory/shared/core_loop_integration_plan.md`, I have created the following sub-issues to implement Phase 1 and Phase 2 of the specialized agent integration:

1. **Issue #132**: Core Loop Integration: Phase 1 - Tool Grouping & Agent Configuration
   - Define tool groups in `brain/tools.py`.
   - Update `AgentConfig` in `brain/config.py`.
   - Update `config.yml` and `agents/*.md`.
2. **Issue #133**: Core Loop Integration: Phase 2 - Dynamic Tool Injection & Runtime Validation
   - Implement tool filtering in `brain/executor.py`.
   - Enforce tool restrictions at runtime.
   - Inject domain-specific system prompts.

I have also commented on the main issue #130 to link these new issues.
This lays the foundation for specialized agent roles (Engineering, Quality, Orchestration) to be formally supported in the brain's logic.