import json
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .llm import DeepSeekLLM
from .memory import SessionMemory
from .chat_memory import ChatMemory
from .permissions import PermissionManager
from .prompts import AGENT_SYSTEM_PROMPT
from .tool_registry import build_tool_registry, render_tool_descriptions
from .custom_types import ChatRequest, Message

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


class AgentLoop:
    def __init__(
        self,
        model: str = None,
        max_steps: int = None,
        root: str = None,
        session_id: str = None,
        chat_id: str = None,
    ) -> None:
        self.model = model if model is not None else config.get("agent.model", "deepseek-chat")
        self.max_steps = max_steps if max_steps is not None else config.get("agent.max_steps", 80)
        self.root = os.path.abspath(root if root is not None else config.get("agent.root", "."))

        self.llm = DeepSeekLLM()
        self.registry = build_tool_registry()
        self.permissions = PermissionManager(self.root)

        storage_path = config.get("agent.session_storage_path", "./sessions")
        chat_storage_path = config.get("agent.chat_storage_path", "./chats")

        self.memory = SessionMemory(storage_path)
        self.chat_memory = ChatMemory(chat_storage_path, storage_path)

        self.session_id = session_id if session_id else str(uuid.uuid4())
        self.chat_id = chat_id if chat_id else self._get_or_create_chat_id()

        self.messages: List[Message] = []
        self.session_started = False
        self.finished = False
        self.pause_requested = False

        self.lock = threading.RLock()

    def _get_or_create_chat_id(self) -> str:
        latest = self.chat_memory.get_latest_chat()
        if latest is not None:
            return latest
        return self.chat_memory.create_chat()

    def _build_current_chat_memory_block(self) -> str:
        meta = self.chat_memory.load_chat_meta(self.chat_id)
        if not meta:
            return ""

        session_ids = meta.get("session_ids", [])
        session_summaries = self.memory.list_session_summaries(session_ids)

        if not meta.get("summary") and not session_summaries:
            return ""

        lines: List[str] = []
        lines.append("以下是当前恢复的历史 chat 记忆。")
        lines.append(f"Current chat id: {self.chat_id}")
        lines.append(f"Chat title: {meta.get('title', '')}")
        lines.append(f"Chat summary: {meta.get('summary', '')}")
        lines.append("")
        lines.append("该 chat 下的 session 摘要列表：")

        for idx, item in enumerate(session_summaries, start=1):
            lines.append(
                f"{idx}. session_id={item.get('session_id', '')}\n"
                f"   title={item.get('title', '')}\n"
                f"   summary={item.get('summary', '')}"
            )

        lines.append("")
        lines.append(
            "如果你需要某个历史 session 的细节，可以使用：\n"
            "- list_chat_session_summaries(chat_id)\n"
            "- read_session_messages(session_id)\n"
            "来按需查看历史原始消息。"
        )

        return "\n".join(lines)

    def start_session(
        self,
        task: str,
        load_existing: bool = False,
        inject_current_chat_memory: bool = True,
    ) -> None:
        with self.lock:
            if load_existing:
                existing_messages = self.memory.load_session(self.session_id)
                if existing_messages:
                    self.messages = existing_messages
                    self.session_started = True
                    self.finished = False
                    self.pause_requested = False
                    self.chat_memory.add_session_to_chat(self.chat_id, self.session_id)
                    print(f"[agent] 已恢复会话: {self.session_id} (chat: {self.chat_id})")
                    return

            tools_text = render_tool_descriptions(self.registry)

            self.messages = [
                Message(role="system", content=AGENT_SYSTEM_PROMPT),
            ]

            if inject_current_chat_memory:
                memory_block = self._build_current_chat_memory_block()
                if memory_block:
                    self.messages.append(
                        Message(
                            role="system",
                            content=memory_block,
                        )
                    )
                    print("[agent] 已注入当前 chat 的摘要记忆")

            self.messages.append(
                Message(
                    role="user",
                    content=(
                        f"Workspace root:\n{self.root}\n\n"
                        f"Current chat id:\n{self.chat_id}\n\n"
                        f"Current session id:\n{self.session_id}\n\n"
                        f"Available tools:\n{tools_text}\n\n"
                        f"Initial task:\n{task}\n\n"
                        "Please explore step by step and help the user complete the task."
                    ),
                ),
            )

            self.session_started = True
            self.finished = False
            self.pause_requested = False

            self.chat_memory.add_session_to_chat(self.chat_id, self.session_id)
            print(f"[agent] 新会话已启动: {self.session_id} (chat: {self.chat_id})")

    def reset_session(self) -> None:
        with self.lock:
            self.messages = []
            self.session_started = False
            self.finished = False
            self.pause_requested = False

    def save_session(self) -> None:
        with self.lock:
            if not self.session_started:
                return
            self.memory.save_session(self.session_id, self.messages)
            self.chat_memory.add_session_to_chat(self.chat_id, self.session_id)

    def load_session(self, session_id: str) -> bool:
        with self.lock:
            messages = self.memory.load_session(session_id)
            if not messages:
                return False

            self.session_id = session_id
            self.messages = messages
            self.session_started = True
            self.finished = False
            self.pause_requested = False
            self.chat_memory.add_session_to_chat(self.chat_id, session_id)
            return True

    def request_pause(self) -> None:
        with self.lock:
            self.pause_requested = True

    def clear_pause(self) -> None:
        with self.lock:
            self.pause_requested = False

    def is_pause_requested(self) -> bool:
        with self.lock:
            return self.pause_requested

    def inject_user_message(self, user_message: str) -> None:
        with self.lock:
            if not self.session_started:
                raise RuntimeError("session 尚未开始，请先调用 start_session()")
            self.messages.append(Message(role="user", content=user_message))
            self.finished = False

    def send_user_message(self, user_message: str) -> str:
        self.inject_user_message(user_message)
        response = self.step_once()
        self.save_session()
        return response

    def _serialize_messages_for_summary(self, messages: List[Message], max_items: int = 80, max_chars: int = 16000) -> str:
        selected = messages[-max_items:]
        blocks: List[str] = []
        total = 0

        for msg in selected:
            block = f"[{msg.role}]\n{msg.content}\n"
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)

        return "\n".join(blocks).strip()

    def _build_session_summary(self, messages: List[Message]) -> Dict[str, Any]:
        raw_text = self._serialize_messages_for_summary(messages)
        prompt = (
            "请把下面这个 session 的对话压缩成结构化摘要。\n\n"
            "输出 JSON：\n"
            "{\n"
            '  "title": "...",\n'
            '  "summary": "...",\n'
            '  "key_points": ["...", "..."]\n'
            "}\n\n"
            "要求：\n"
            "1. 重点保留已完成的工作、关键决策、当前状态、未完成事项。\n"
            "2. 删除寒暄和重复内容。\n"
            "3. title 要具体。\n\n"
            f"原始内容如下：\n{raw_text}"
        )

        try:
            resp = self.llm.chat(
                ChatRequest(
                    model=self.model,
                    messages=[
                        Message(role="system", content="你是一个负责压缩工程 session 记忆的助手。"),
                        Message(role="user", content=prompt),
                    ],
                )
            )
            data = self._parse_json(resp.content.strip())
            return {
                "title": data.get("title", f"Session {self.session_id[:8]}"),
                "summary": data.get("summary", ""),
                "key_points": data.get("key_points", []),
                "chat_id": self.chat_id,
                "session_id": self.session_id,
                "updated_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            print(f"[agent] 生成 session 摘要失败，使用 fallback: {e}")
            return {
                "title": f"Session {self.session_id[:8]}",
                "summary": raw_text[:1000],
                "key_points": [],
                "chat_id": self.chat_id,
                "session_id": self.session_id,
                "updated_at": datetime.utcnow().isoformat(),
            }

    def _build_chat_summary(self, session_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        chat_meta = self.chat_memory.load_chat_meta(self.chat_id) or {}

        summary_blocks: List[str] = []
        for idx, item in enumerate(session_summaries, start=1):
            summary_blocks.append(
                f"{idx}. session_id={item.get('session_id', '')}\n"
                f"title={item.get('title', '')}\n"
                f"summary={item.get('summary', '')}"
            )

        prompt = (
            "请根据以下多个 session 摘要，更新这个 chat 的整体标题和摘要。\n\n"
            "输出 JSON：\n"
            "{\n"
            '  "title": "...",\n'
            '  "summary": "..."\n'
            "}\n\n"
            "要求：\n"
            "1. title 概括整个 chat 的长期主题。\n"
            "2. summary 概括整体进展，而不是单次 session。\n"
            "3. 如果已有标题/摘要合理，请延续其方向更新。\n\n"
            f"已有 chat 标题：{chat_meta.get('title', '')}\n"
            f"已有 chat 摘要：{chat_meta.get('summary', '')}\n\n"
            "各 session 摘要如下：\n"
            + "\n\n".join(summary_blocks)
        )

        try:
            resp = self.llm.chat(
                ChatRequest(
                    model=self.model,
                    messages=[
                        Message(role="system", content="你是一个负责维护 chat 长期记忆摘要的助手。"),
                        Message(role="user", content=prompt),
                    ],
                )
            )
            data = self._parse_json(resp.content.strip())
            return {
                "chat_id": self.chat_id,
                "title": data.get("title", chat_meta.get("title", "新会话")),
                "summary": data.get("summary", chat_meta.get("summary", "")),
                "session_ids": [x["session_id"] for x in session_summaries],
            }
        except Exception as e:
            print(f"[agent] 生成 chat 摘要失败，使用 fallback: {e}")
            fallback_summary = "\n".join(
                f"- {x.get('title', '')}: {x.get('summary', '')[:200]}"
                for x in session_summaries[-10:]
            )
            return {
                "chat_id": self.chat_id,
                "title": chat_meta.get("title", "新会话"),
                "summary": fallback_summary,
                "session_ids": [x["session_id"] for x in session_summaries],
            }

    def finalize_session_memory(self) -> None:
        with self.lock:
            if not self.session_started or not self.messages:
                return
            session_messages = list(self.messages)
            session_id = self.session_id
            chat_id = self.chat_id

        session_summary = self._build_session_summary(session_messages)
        self.memory.save_session_summary(session_id, session_summary)

        sessions = self.chat_memory.get_chat_sessions(chat_id)
        session_ids = [s["session_id"] for s in sessions]
        session_summaries = self.memory.list_session_summaries(session_ids)

        chat_meta = self._build_chat_summary(session_summaries)
        self.chat_memory.save_chat_meta(chat_id, chat_meta)

        print(f"[agent] 已更新 session 摘要: {session_id}")
        print(f"[agent] 已更新 chat 摘要: {chat_id}")

    def step_once(self) -> str:
        with self.lock:
            if not self.session_started:
                raise RuntimeError("session 尚未开始，请先调用 start_session()")

            if self.finished:
                return "当前 session 已完成。你可以继续补充信息，或者 /reset 开始新任务。"

            messages_snapshot = list(self.messages)

        print("\n[agent] 正在请求模型...", flush=True)
        response = self.llm.chat(ChatRequest(messages=messages_snapshot, model=self.model))
        raw_text = response.content.strip()

        action_obj = self._parse_json(raw_text)
        action = action_obj.get("action")

        lines: List[str] = []
        lines.append("===== AGENT ACTION =====")
        lines.append(raw_text)

        with self.lock:
            self.messages.append(Message(role="assistant", content=raw_text))

        if action == "final":
            final_answer = action_obj.get("final_answer", "").strip()
            with self.lock:
                self.finished = True

            self.save_session()
            self.finalize_session_memory()

            lines.append("\n===== FINAL ANSWER =====")
            lines.append(final_answer or "(empty final answer)")
            return "\n".join(lines)

        if action != "tool":
            raise RuntimeError(f"模型返回了未知 action: {action_obj}")

        tool_name = action_obj.get("tool_name", "")
        tool_args = action_obj.get("tool_args", {})

        if tool_name not in self.registry:
            raise RuntimeError(f"模型请求了未知工具: {tool_name}")

        tool_feedback = self._execute_tool_or_permission_result(tool_name, tool_args)

        with self.lock:
            self.messages.append(
                Message(
                    role="user",
                    content=(
                        "Tool execution result:\n"
                        f"{json.dumps(tool_feedback, ensure_ascii=False, indent=2)}\n\n"
                        "Interpretation rules:\n"
                        "1. If ok is true, the tool executed successfully.\n"
                        "2. Only treat permission as blocked when meta.blocked_by_permission is true,\n"
                        "   or the content explicitly says the user did not grant permission.\n"
                        "3. Do NOT infer permission problems merely because filenames, paths, or text\n"
                        "   contain words like 'permission', 'permissions', '权限', or similar.\n"
                        "4. If ok is true, continue the task based on the actual tool result.\n\n"
                        "Based on this result, decide the next action."
                    ),
                )
            )

        self.save_session()

        lines.append("\n===== TOOL RESULT =====")
        lines.append(json.dumps(tool_feedback, ensure_ascii=False, indent=2))

        return "\n".join(lines)

    def _execute_tool_or_permission_result(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        permission_feedback = self._maybe_request_permission(tool_name, tool_args)
        if permission_feedback is not None:
            return {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "ok": False,
                "content": permission_feedback,
                "meta": {
                    "blocked_by_permission": True,
                },
            }

        tool = self.registry[tool_name]
        tool_result = tool.run(**tool_args)

        print("[tool_feedback]", json.dumps({
                "tool_name": tool_name,
                "tool_args": tool_args,
                "ok": tool_result.ok,
                "content": tool_result.content[:300] if isinstance(tool_result.content, str) else str(tool_result.content),
                "meta": tool_result.meta or {},
            }, ensure_ascii=False))
        return {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "ok": tool_result.ok,
            "content": tool_result.content,
            "meta": tool_result.meta or {},
        }

    def _maybe_request_permission(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        # TEMP: disable all permission blocking
        return None

    def _ask_user_for_permission(
        self,
        command: str,
        cwd: Optional[str],
        requested_paths: List[str],
        reason: str,
    ) -> bool:
        # TEMP: always allow
        return True

    def _parse_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()

        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1])

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        raise RuntimeError(f"模型输出不是合法 JSON:\n{text}")