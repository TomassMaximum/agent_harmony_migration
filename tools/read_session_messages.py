import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from agent.memory import SessionMemory
from .base import BaseTool, ToolResult


class ReadSessionMessagesTool(BaseTool):
    name = "read_session_messages"
    description = "读取某个 session 的原始消息内容。参数: session_id, max_messages(可选), max_chars(可选)"

    def __init__(self) -> None:
        storage_path = config.get("agent.session_storage_path", "./sessions")
        self.memory = SessionMemory(storage_path)

    def run(self, **kwargs) -> ToolResult:
        session_id = kwargs.get("session_id")
        max_messages = kwargs.get("max_messages", 50)
        max_chars = kwargs.get("max_chars", 12000)

        if not isinstance(session_id, str) or not session_id.strip():
            return ToolResult(ok=False, content="参数 session_id 无效")

        try:
            max_messages = int(max_messages)
        except Exception:
            max_messages = 50

        try:
            max_chars = int(max_chars)
        except Exception:
            max_chars = 12000

        messages = self.memory.load_session(session_id)
        if not messages:
            return ToolResult(ok=False, content=f"session 不存在或没有消息: {session_id}")

        selected = messages[-max_messages:]
        lines = []
        total = 0
        for msg in selected:
            block = f"[{msg.role}]\n{msg.content}\n"
            if total + len(block) > max_chars:
                break
            lines.append(block)
            total += len(block)

        return ToolResult(ok=True, content="\n".join(lines).strip())