 visionary
# Coding Standards for FOREMAN Agent

## 1. Core Principles
- **SOLID**: Follow Single Responsibility, Open/Closed, Liskov Substitutionthink
串# Coding Standards for FOREMAN Agent

## 1. Core Principles
- **SOLID**: Follow Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, and Dependency Inversion.
- **DRY (Don't Repeat Yourself)**: Abstract common logic into utilities or base classes.
- **KISS (Keep It Simple, Stupid)**: Avoid over-engineering. Prefer readable code over clever code.

## 2. Python Specifics
- **Naming**: Use `snake_case` for functions/variables, `PascalCase` for classes, and `SCREAMING_SNAKE_CASE` for constants.
- **Type Hinting**: Provide type hints for function arguments and return values where possible.
- **Docstrings**: Use clear docstrings for classes and public methods.

## 3. Autonomous Agent Safety
- **Error Handling**: Every major logical block or loop must be wrapped in `try/except` to prevent agent crashes.
- **No Unhandled Exceptions**: Log the exception and decide whether to `continue`, `break`, or `return`.
- **Atomic Writes**: Ensure file operations are handled carefully to prevent data loss.

## 4. Logging Patterns
- Use the standard `logging` library.
- Log entry points, significant decision branches, and all errors.
- Ensure logs provide enough context for a human to debug the agent's autonomous path.

## 5. File Structure
- Keep files focused on a single component (e.g., `agent.py`, `utils.py`, `config.py`).
- Imports should be grouped: standard library, third-party packages, local modules.

## 6. Code Review Guidelines
- Reviews must check for adherence to these standards.
- Cite specific sections of this document (e.g., "Violates Section 3: Missing try/except block").
- Suggest specific refactors for DRY violations.

## 7. Implementation Guidelines
- Match existing repository style (indentation, line breaks).
- No preamble or conversational filler in code output.
- Start file content at character 0.