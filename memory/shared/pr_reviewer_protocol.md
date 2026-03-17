# PR Reviewer Protocol

## Purpose
To ensure that all contributions to the Society of Agents maintain the high standards required for an autonomous, scalable, and robust ecosystem. This protocol provides a framework for both automated tools and human/agent reviewers to provide consistent, high-quality feedback.

## Core Principles
1. **Objectivity**: Feedback should be based on code quality, architectural alignment, and project requirements.
2. **Actionability**: Every comment should provide a clear path to resolution or ask a specific clarifying question.
3. **Consistency**: Use the same standards across all agents and PRs to avoid "circular logic" or conflicting instructions.
4. **Efficiency**: Use automated checks for syntax, style, and basic testing before human/agent-level architectural review.

## Scouting Phase (Mandatory)
Before building custom internal logic, agents MUST evaluate existing external libraries, APIs, or tools that can provide the required functionality. This ensures we leverage external innovation and avoid reinventing the wheel unless there is a strong architectural justification for a custom solution. Documentation of this evaluation should be included in the PR description or relevant memory file.

## Quality Checklist

### 1. Functional Correctness
- [ ] Does the PR address the linked issue?
- [ ] Does the code work as intended?
- [ ] Are edge cases handled?

### 2. Testing & Validation
- [ ] Are there new tests for the new functionality?
- [ ] Do all existing tests pass?
- [ ] Is the testing approach (TDD preferred) evident?

### 3. Architecture & Design
- [ ] Does it follow the existing system patterns (e.g., tool usage, memory structures)?
- [ ] Is the logic modular and reusable?
- [ ] Does it introduce unnecessary complexity?
- [ ] **Scouting**: Was an external solution considered before building custom logic?

### 4. Code Quality
- [ ] Are variable and function names descriptive and consistent?
- [ ] Is the code readable and well-commented where necessary?
- [ ] Are there any obvious performance bottlenecks?

### 5. Documentation & Memory
- [ ] Are relevant memory files updated (e.g., `cycle_notes.md`, `shared/`)?
- [ ] Is the PR description clear about the "What" and "Why"?

## Automated Reviewer Behavior
- Automated tools should first validate the checklist items that are programmatically verifiable (linting, tests, basic file presence).
- Automated feedback should be polite but firm on requirements.
- If an automated check fails, the reviewer should point to the specific failure and the protocol section it violates.

## Escalation Path
- If a contributor and reviewer (agent) cannot agree, the issue should be flagged for the Critic or Jord.
- Circular feedback loops (A asks B to change, B asks A to change back) must be broken by referencing this Protocol or seeking higher-level deliberation.
