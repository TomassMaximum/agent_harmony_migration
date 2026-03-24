import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .custom_types import Message


class SessionMemory:
    def __init__(self, storage_path: str) -> None:
        self.storage_path = os.path.abspath(storage_path)
        self.raw_dir = os.path.join(self.storage_path, "raw")
        self.summary_dir = os.path.join(self.storage_path, "summaries")

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.summary_dir, exist_ok=True)

    def _raw_path(self, session_id: str) -> str:
        return os.path.join(self.raw_dir, f"{session_id}.json")

    def _summary_path(self, session_id: str) -> str:
        return os.path.join(self.summary_dir, f"{session_id}.json")

    def save_session(self, session_id: str, messages: List[Message]) -> None:
        data = {
            "session_id": session_id,
            "updated_at": datetime.utcnow().isoformat(),
            "messages": [
                {
                    "role": getattr(msg, "role", ""),
                    "content": getattr(msg, "content", ""),
                }
                for msg in messages
            ],
        }
        with open(self._raw_path(session_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_session(self, session_id: str) -> List[Message]:
        path = self._raw_path(session_id)
        if not os.path.isfile(path):
            return []

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        result: List[Message] = []
        for item in data.get("messages", []):
            result.append(
                Message(
                    role=item.get("role", ""),
                    content=item.get("content", ""),
                )
            )
        return result

    def delete_session(self, session_id: str) -> None:
        raw_path = self._raw_path(session_id)
        summary_path = self._summary_path(session_id)

        if os.path.isfile(raw_path):
            os.remove(raw_path)
        if os.path.isfile(summary_path):
            os.remove(summary_path)

    def save_session_summary(self, session_id: str, summary_data: Dict[str, Any]) -> None:
        data = dict(summary_data)
        data["session_id"] = session_id
        data["updated_at"] = data.get("updated_at") or datetime.utcnow().isoformat()

        with open(self._summary_path(session_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        path = self._summary_path(session_id)
        if not os.path.isfile(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_session_summaries(self, session_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []

        if session_ids is None:
            files = [f for f in os.listdir(self.summary_dir) if f.endswith(".json")]
            session_ids = [os.path.splitext(f)[0] for f in files]

        for session_id in session_ids:
            item = self.load_session_summary(session_id)
            if item:
                result.append(item)

        result.sort(key=lambda x: x.get("updated_at", ""), reverse=False)
        return result