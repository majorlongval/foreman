from abc import ABC, abstractmethod
from typing import Any, Dict, List

class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        pass

class ToolExecutor(ABC):
    @abstractmethod
    def register_tool(self, tool: Tool) -> None:
        pass

    @abstractmethod
    def execute(self, tool_name: str, **kwargs) -> Any:
        pass

    @abstractmethod
    def get_costs(self) -> Dict[str, float]:
        pass
