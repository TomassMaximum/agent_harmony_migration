import json
import os
from typing import List, Optional, Dict, Any
from .types import Message


class SessionMemory:
    """会话记忆存储管理器"""

    def __init__(self, storage_path: str = "./sessions"):
        """
        初始化存储管理器
        :param storage_path: 会话存储目录路径
        """
        self.storage_path = os.path.abspath(storage_path)
        os.makedirs(self.storage_path, exist_ok=True)

    def session_file(self, session_id: str) -> str:
        """返回会话文件路径"""
        return os.path.join(self.storage_path, f"{session_id}.json")

    def save_session(self, session_id: str, messages: List[Message], metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        保存会话到文件
        :param session_id: 会话ID
        :param messages: 消息列表
        :param metadata: 可选元数据（如摘要、创建时间等）
        """
        data = {
            "session_id": session_id,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "metadata": metadata or {}
        }
        file_path = self.session_file(session_id)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_session(self, session_id: str) -> Optional[List[Message]]:
        """
        从文件加载会话消息
        :param session_id: 会话ID
        :return: 消息列表，如果不存在则返回None
        """
        file_path = self.session_file(session_id)
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            messages = [Message(role=msg["role"], content=msg["content"]) for msg in data.get("messages", [])]
            return messages
        except (json.JSONDecodeError, KeyError, IOError):
            return None

    def delete_session(self, session_id: str) -> bool:
        """删除会话文件"""
        file_path = self.session_file(session_id)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False

    def list_sessions(self) -> List[str]:
        """列出所有会话ID"""
        if not os.path.exists(self.storage_path):
            return []
        sessions = []
        for filename in os.listdir(self.storage_path):
            if filename.endswith(".json"):
                sessions.append(filename[:-5])  # 去掉 .json
        return sessions
