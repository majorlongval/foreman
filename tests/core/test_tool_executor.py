import pytest
from foreman.core.interfaces import Tool, ToolExecutor
from foreman.core.executor import DefaultToolExecutor

class MockTool(Tool):
    @property
    def name(self): return "mock_tool"
    @property
    def description(self): return "A mock tool for testing"
    def execute(self, **kwargs): return "success"

def test_tool_registration():
    executor = DefaultToolExecutor()
    tool = MockTool()
    executor.register_tool(tool)
    assert "mock_tool" in executor.list_tools()

def test_tool_execution():
    executor = DefaultToolExecutor()
    executor.register_tool(MockTool())
    result = executor.execute("mock_tool")
    assert result == "success"

def test_cost_logging():
    executor = DefaultToolExecutor()
    executor.register_tool(MockTool())
    executor.execute("mock_tool")
    assert executor.get_costs()["mock_tool"] > 0
