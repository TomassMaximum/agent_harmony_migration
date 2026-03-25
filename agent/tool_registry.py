from typing import Any, Dict

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


def render_tool_command(tool_name: str, tool_args: Dict[str, Any]) -> str:
    tool_args = tool_args or {}

    if tool_name == "run_command":
        return str(tool_args.get("command", "")).strip()

    if tool_name == "list_dir":
        path = str(tool_args.get("path", ".")).strip()
        return f"ls {path}"

    if tool_name == "read_file":
        path = str(tool_args.get("path", "")).strip()
        return f"cat {path}" if path else ""

    if tool_name == "search_text":
        keyword = str(tool_args.get("keyword", "")).strip()
        path = str(tool_args.get("path", ".")).strip()
        if keyword:
            return f'grep -R "{keyword}" {path}'
        return f"grep -R <text> {path}"

    if tool_name == "which_command":
        command_name = str(tool_args.get("command_name", "")).strip()
        return f"which {command_name}" if command_name else "which <command>"

    if tool_name == "get_env_var":
        name = str(tool_args.get("name", "")).strip()
        return f"echo ${name}" if name else "printenv"

    if tool_name == "read_session_messages":
        session_id = str(tool_args.get("session_id", "")).strip()
        return f"read_session_messages {session_id}".strip()

    if tool_name == "list_chat_session_summaries":
        chat_id = str(tool_args.get("chat_id", "")).strip()
        return f"list_chat_session_summaries {chat_id}".strip()

    return tool_name