import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from agent.memory import SessionMemory
from agent.chat_memory import ChatMemory
from .base import BaseTool, ToolResult


class ListChatSessionSummariesTool(BaseTool):
    name = "list_chat_session_summaries"
    description = "列出某个 chat 下所有 session 的摘要。参数: chat_id"

    def __init__(self) -> None:
        storage_path = config.get("agent.session_storage_path", "./sessions")
        chat_storage_path = config.get("agent.chat_storage_path", "./chats")
        self.memory = SessionMemory(storage_path)
        self.chat_memory = ChatMemory(chat_storage_path, storage_path)

    def run(self, **kwargs) -> ToolResult:
        chat_id = kwargs.get("chat_id")
        if not isinstance(chat_id, str) or not chat_id.strip():
            return ToolResult(ok=False, content="参数 chat_id 无效")

        sessions = self.chat_memory.get_chat_sessions(chat_id)
        session_ids = [s["session_id"] for s in sessions]
        summaries = self.memory.list_session_summaries(session_ids)

        if not summaries:
            return ToolResult(ok=True, content="[]")

        simplified = []
        for item in summaries:
            simplified.append(
                {
                    "session_id": item.get("session_id", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "updated_at": item.get("updated_at", ""),
                }
            )

        return ToolResult(ok=True, content=json.dumps(simplified, ensure_ascii=False, indent=2))