from typing import Dict

from tools import (
    GetEnvVarTool,
    ListDirTool,
    ListChatSessionSummariesTool,
    ReadFileTool,
    ReadSessionMessagesTool,
    RunCommandTool,
    SearchTextTool,
    WhichCommandTool,
)
from tools.base import BaseTool


def build_tool_registry() -> Dict[str, BaseTool]:
    tools = [
        ListDirTool(),
        ReadFileTool(),
        SearchTextTool(),
        RunCommandTool(),
        WhichCommandTool(),
        GetEnvVarTool(),
        ListChatSessionSummariesTool(),
        ReadSessionMessagesTool(),
    ]
    return {tool.name: tool for tool in tools}


def render_tool_descriptions(registry: Dict[str, BaseTool]) -> str:
    lines = []
    for tool in registry.values():
        lines.append(f"- {tool.name}: {tool.description}")
    return "\n".join(lines)