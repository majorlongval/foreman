# Brain Hardening Plan: Strict Internal Communication

## Objective
To eliminate recurring JSON parsing failures by enforcing strict Pydantic schemas for all internal communications and tool interactions. This "Brain Hardening" process ensures that all data flowing through the system is validated against expected structures.

## Protocol Standards
1. **Pydantic Everywhere**: All data structures passed between agents, stored in memory, or passed to tools must be defined as Pydantic models.
2. **Strict Validation**: Models must use `ConfigDict(extra='forbid')` where possible to prevent unexpected fields from causing silent failures or parsing ambiguity.
3. **Type Safety**: Leverage Python type hints and Pydantic validation to catch errors at the boundary of agent logic.
4. **Schema Documentation**: Every schema must include descriptions for each field to aid LLM understanding during tool selection.

## Implementation Steps
1. **Core Schema Definition**: Define base Pydantic models for:
    - Agent-to-Agent Messages
    - Tool Input/Output envelopes
    - Memory storage formats
2. **Tool Definition Refactoring**: Update all `tool_schemas` to be auto-generated from Pydantic models rather than manually written JSON schemas.
3. **Parsing Middleware**: Implement a standard parsing layer that catches `ValidationError` and returns structured error messages to the calling agent, allowing them to self-correct.
4. **Migration Path**: 
    - Identify current high-failure points (e.g., complex nested JSON).
    - Replace raw dict manipulation with Pydantic model methods (`.model_dump()`, `.model_validate_json()`).

## Validation Error Handling
When validation fails, the system should return a clear, structured error:
```json
{
  "status": "error",
  "error_type": "ValidationError",
  "details": [
    {
      "loc": ["field_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ],
  "hint": "Please ensure the JSON matches the schema provided in the tool definition."
}
```

## Expected Outcomes
- 99% reduction in `JSONDecodeError` and field missing errors.
- Improved agent reliability when handling complex data.
- Faster debugging via specific validation messages.
