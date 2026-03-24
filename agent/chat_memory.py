import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


class ChatMemory:
    def __init__(self, chat_storage_path: str, session_storage_path: str = None) -> None:
        self.chat_storage_path = os.path.abspath(chat_storage_path)
        self.meta_dir = os.path.join(self.chat_storage_path, "meta")
        os.makedirs(self.meta_dir, exist_ok=True)

    def _meta_path(self, chat_id: str) -> str:
        return os.path.join(self.meta_dir, f"{chat_id}.json")

    def create_chat(self) -> str:
        chat_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        data = {
            "chat_id": chat_id,
            "title": "新会话",
            "summary": "",
            "session_ids": [],
            "created_at": now,
            "updated_at": now,
        }
        self.save_chat_meta(chat_id, data)
        return chat_id

    def save_chat_meta(self, chat_id: str, meta: Dict[str, Any]) -> None:
        current = self.load_chat_meta(chat_id) or {}

        data = dict(current)
        data.update(meta)

        data["chat_id"] = chat_id
        data["session_ids"] = data.get("session_ids", [])
        data["created_at"] = data.get("created_at") or datetime.utcnow().isoformat()
        data["updated_at"] = datetime.utcnow().isoformat()

        with open(self._meta_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_chat_meta(self, chat_id: str) -> Optional[Dict[str, Any]]:
        path = self._meta_path(chat_id)
        if not os.path.isfile(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_latest_chat(self) -> Optional[str]:
        chats = self.list_recent_chat_meta(limit=1)
        if not chats:
            return None
        return chats[0]["chat_id"]

    def get_previous_chat_id(self, current_chat_id: str) -> Optional[str]:
        chats = self.list_recent_chat_meta(limit=1000)
        ids = [c["chat_id"] for c in chats]
        if current_chat_id not in ids:
            return None

        idx = ids.index(current_chat_id)
        if idx + 1 < len(ids):
            return ids[idx + 1]
        return None

    def add_session_to_chat(self, chat_id: str, session_id: str) -> None:
        meta = self.load_chat_meta(chat_id)
        if meta is None:
            meta = {
                "chat_id": chat_id,
                "title": "新会话",
                "summary": "",
                "session_ids": [],
                "created_at": datetime.utcnow().isoformat(),
            }

        session_ids = meta.get("session_ids", [])
        if session_id not in session_ids:
            session_ids.append(session_id)

        meta["session_ids"] = session_ids
        self.save_chat_meta(chat_id, meta)

    def get_chat_sessions(self, chat_id: str) -> List[Dict[str, Any]]:
        meta = self.load_chat_meta(chat_id)
        if not meta:
            return []

        result = []
        for sid in meta.get("session_ids", []):
            result.append({"session_id": sid})
        return result

    def list_recent_chat_meta(self, limit: int = 10) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []

        for filename in os.listdir(self.meta_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self.meta_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    result.append(json.load(f))
            except Exception:
                continue

        result.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return result[:limit]

    def list_chats(self) -> List[str]:
        chats = self.list_recent_chat_meta(limit=1000)
        return [c["chat_id"] for c in chats]