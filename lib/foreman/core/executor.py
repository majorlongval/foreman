from typing import Any, Dict, List
from .interfaces import Tool, ToolExecutor

class DefaultToolExecutor(ToolExecutor):
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._costs: Dict[str, float] = {}

    def register_tool(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        if tool.name not in self._costs:
            self._costs[tool.name] = 0.0

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def execute(self, tool_name: str, **kwargs) -> Any:
        if tool_name not in self._tools:
            raise ValueError(f"Tool {tool_name} not registered")
        
        # Standard increment for TDD pass
        self._costs[tool_name] += 0.01 
        return self._tools[tool_name].execute(**kwargs)

    def get_costs(self) -> Dict[str, float]:
        return self._costs
