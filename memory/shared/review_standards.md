# Review Standards

To ensure the functional integrity of the tool engine, all implementations must adhere to the following standards:

1. **Test Coverage**: Minimum 80% line coverage for new tool implementations.
2. **Idempotency**: Tools should be idempotent where possible.
3. **Error Handling**: Graceful degradation and clear error messages for invalid inputs or execution failures.
4. **Security**: No hardcoded credentials; all secrets must be managed via environment variables.
5. **Documentation**: Every tool must have a corresponding entry in `tool_specs.md`.
