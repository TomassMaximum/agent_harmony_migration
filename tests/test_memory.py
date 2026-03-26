import tempfile
import unittest
from pathlib import Path

from agent.chat_memory import ChatMemory
from agent.custom_types import Message
from agent.memory import SessionMemory


class SessionMemoryTest(unittest.TestCase):
    def test_save_and_load_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = SessionMemory(tmpdir)
            session_id = "session-1"
            messages = [
                Message(role="system", content="hello"),
                Message(role="user", content="world"),
            ]

            memory.save_session(session_id, messages)
            loaded = memory.load_session(session_id)

            self.assertEqual([m.role for m in loaded], ["system", "user"])
            self.assertEqual([m.content for m in loaded], ["hello", "world"])

    def test_save_and_list_session_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = SessionMemory(tmpdir)
            memory.save_session_summary("s1", {"title": "A", "summary": "first", "updated_at": "2024-01-01T00:00:00"})
            memory.save_session_summary("s2", {"title": "B", "summary": "second", "updated_at": "2024-01-02T00:00:00"})

            summaries = memory.list_session_summaries(["s1", "s2"])

            self.assertEqual([item["session_id"] for item in summaries], ["s1", "s2"])
            self.assertEqual(summaries[0]["title"], "A")
            self.assertEqual(summaries[1]["title"], "B")


class ChatMemoryTest(unittest.TestCase):
    def test_create_chat_and_add_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_memory = ChatMemory(tmpdir)

            chat_id = chat_memory.create_chat()
            chat_memory.add_session_to_chat(chat_id, "session-1")
            chat_memory.add_session_to_chat(chat_id, "session-1")

            meta = chat_memory.load_chat_meta(chat_id)
            self.assertIsNotNone(meta)
            self.assertEqual(meta["chat_id"], chat_id)
            self.assertEqual(meta["session_ids"], ["session-1"])

    def test_list_recent_chat_meta_skips_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_memory = ChatMemory(tmpdir)
            valid_chat_id = chat_memory.create_chat()

            broken_path = Path(tmpdir) / "meta" / "broken.json"
            broken_path.write_text("{", encoding="utf-8")

            recent = chat_memory.list_recent_chat_meta(limit=10)

            self.assertTrue(any(item["chat_id"] == valid_chat_id for item in recent))


if __name__ == "__main__":
    unittest.main()
