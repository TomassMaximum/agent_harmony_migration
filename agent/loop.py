import json
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Generator, List, Optional

from .llm import create_llm
from .memory import SessionMemory
from .chat_memory import ChatMemory
from .permissions import PermissionDecision, PermissionManager
from .prompts import (
    AGENT_SYSTEM_PROMPT,
    CHAT_SUMMARY_SYSTEM_PROMPT,
    SESSION_SUMMARY_SYSTEM_PROMPT,
    build_chat_summary_prompt,
    build_current_chat_memory_block,
    build_session_start_message,
    build_session_summary_prompt,
    build_tool_feedback_message,
)
from .tool_registry import build_tool_registry, render_tool_descriptions, render_tool_command
from .custom_types import ChatRequest, Message, RunResult
from .errors import AgentExecutionError, InvalidModelOutputError, LLMExecutionError, ToolExecutionError
from .events import AgentEvent

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


class AgentLoop:
    def __init__(
        self,
        llm_name: str = None,
        provider: str = None,
        model: str = None,
        max_steps: int = None,
        root: str = None,
        session_id: str = None,
        chat_id: str = None,
        permission_approval_handler: Optional[Callable[[str, Optional[str], PermissionDecision], bool]] = None,
    ) -> None:
        llm_config = config.get_llm_config(llm_name)
        self.llm_name = llm_config["name"]
        self.provider = provider if provider is not None else llm_config.get("provider", "deepseek")
        self.model = model if model is not None else llm_config.get("model", "deepseek-chat")
        self.max_steps = max_steps if max_steps is not None else config.get("agent.max_steps", 80)
        self.root = os.path.abspath(root if root is not None else config.get("agent.root", "."))

        self.llm = create_llm(llm_name=self.llm_name, provider=self.provider)
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
        self.permission_approval_handler = permission_approval_handler

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
        return build_current_chat_memory_block(self.chat_id, meta, session_summaries)

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

            self.messages.append(
                Message(
                    role="user",
                    content=build_session_start_message(
                        root=self.root,
                        chat_id=self.chat_id,
                        session_id=self.session_id,
                        tools_text=tools_text,
                        task=task,
                    ),
                ),
            )

            self.session_started = True
            self.finished = False
            self.pause_requested = False

            self.chat_memory.add_session_to_chat(self.chat_id, self.session_id)

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

    def _save_session_best_effort(self) -> None:
        try:
            self.save_session()
        except Exception:
            pass

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
        result = self.run_until_stop()

        if result.stop_reason == "final" and result.final_answer:
            return result.final_answer
        return result.user_facing_text()

    def _extract_final_answer(self, events: List[AgentEvent]) -> str:
        for event in reversed(events):
            if event.type == "final" and event.content:
                return event.content.strip()
        return ""

    def _extract_permission_blocked_message(self, events: List[AgentEvent]) -> str:
        for event in reversed(events):
            if event.type != "tool_result" or not isinstance(event.result, dict):
                continue

            meta = event.result.get("meta") or {}
            if not isinstance(meta, dict):
                continue

            if not meta.get("blocked_by_permission"):
                continue

            content = event.result.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
            return "本轮执行因权限限制而停止。"

        return ""

    def _iter_until_stop(
        self,
        max_steps: Optional[int] = None,
    ) -> Generator[List[AgentEvent], None, RunResult]:
        with self.lock:
            if not self.session_started:
                raise RuntimeError("session 尚未开始，请先调用 start_session()")

        step_limit = self.max_steps if max_steps is None else max_steps
        if not isinstance(step_limit, int):
            step_limit = self.max_steps
        if step_limit < 0:
            step_limit = 0

        all_events: List[AgentEvent] = []
        step_count = 0

        while step_count < step_limit:
            try:
                step_events = self.step_once()
            except Exception as e:
                stop_reason = "error"
                if isinstance(e, AgentExecutionError):
                    stop_reason = e.stop_reason
                failed_step_count = max(1, step_count + 1)

                self._save_session_best_effort()

                error_event = AgentEvent(
                    type="error",
                    step=failed_step_count,
                    content=str(e),
                )
                all_events.append(error_event)
                yield [error_event]

                return RunResult(
                    final_answer=self._extract_final_answer(all_events),
                    stop_reason=stop_reason,
                    step_count=failed_step_count,
                    events=all_events,
                    chat_id=self.chat_id,
                    session_id=self.session_id,
                    error_message=str(e),
                )

            if step_events:
                all_events.extend(step_events)
                yield step_events

            step_count += 1

            permission_message = self._extract_permission_blocked_message(step_events)
            if permission_message:
                return RunResult(
                    final_answer=self._extract_final_answer(all_events),
                    stop_reason="permission_blocked",
                    step_count=step_count,
                    events=all_events,
                    chat_id=self.chat_id,
                    session_id=self.session_id,
                    error_message=permission_message,
                )

            final_answer = self._extract_final_answer(step_events)
            if final_answer:
                return RunResult(
                    final_answer=final_answer,
                    stop_reason="final",
                    step_count=step_count,
                    events=all_events,
                    chat_id=self.chat_id,
                    session_id=self.session_id,
                )

        self._save_session_best_effort()
        return RunResult(
            final_answer=self._extract_final_answer(all_events),
            stop_reason="max_steps",
            step_count=step_count,
            events=all_events,
            chat_id=self.chat_id,
            session_id=self.session_id,
        )

    def run_until_stop(
        self,
        max_steps: Optional[int] = None,
        on_step: Optional[Callable[[List[AgentEvent]], None]] = None,
    ) -> RunResult:
        runner = self._iter_until_stop(max_steps=max_steps)
        while True:
            try:
                step_events = next(runner)
                if on_step:
                    on_step(step_events)
            except StopIteration as stop:
                return stop.value
        
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
        prompt = build_session_summary_prompt(raw_text)

        try:
            resp = self.llm.chat(
                ChatRequest(
                    model=self.model,
                    messages=[
                        Message(role="system", content=SESSION_SUMMARY_SYSTEM_PROMPT),
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
        prompt = build_chat_summary_prompt(chat_meta, session_summaries)

        try:
            resp = self.llm.chat(
                ChatRequest(
                    model=self.model,
                    messages=[
                        Message(role="system", content=CHAT_SUMMARY_SYSTEM_PROMPT),
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

    def _normalize_action_payload(self, action_obj: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(action_obj or {})
        action = str(normalized.get("action") or "").strip()
        tool_name = str(normalized.get("tool_name") or "").strip()

        if action == "final":
            normalized["action"] = "final"
            return normalized

        if action == "tool":
            normalized["action"] = "tool"
            return normalized

        # 兼容部分模型直接把 action 输出成工具名。
        if action in self.registry:
            normalized["action"] = "tool"
            if not tool_name:
                normalized["tool_name"] = action
            return normalized

        # 兼容 action 缺失但 tool_name 正常的情况。
        if not action and tool_name in self.registry:
            normalized["action"] = "tool"
            return normalized

        return normalized

    def step_once(self) -> List[AgentEvent]:
        with self.lock:
            if not self.session_started:
                raise RuntimeError("session 尚未开始，请先调用 start_session()")

            if self.finished:
                return [
                    AgentEvent(
                        type="final",
                        step=0,
                        content="当前 session 已完成。你可以继续补充信息，或者 /reset 开始新任务。"
                    )
                ]

            messages_snapshot = list(self.messages)

        try:
            response = self.llm.chat(ChatRequest(messages=messages_snapshot, model=self.model))
        except Exception as e:
            raise LLMExecutionError(f"模型请求失败：{e}") from e

        raw_text = response.content.strip()

        try:
            action_obj = self._parse_json(raw_text)
        except Exception as e:
            raise InvalidModelOutputError(str(e)) from e

        action_obj = self._normalize_action_payload(action_obj)

        action = action_obj.get("action")
        thought = (action_obj.get("thought") or "").strip()

        with self.lock:
            self.messages.append(Message(role="assistant", content=raw_text))

        step_no = max(1, sum(1 for m in messages_snapshot if m.role == "assistant") + 1)
        events: List[AgentEvent] = []

        if thought:
            events.append(
                AgentEvent(
                    type="thought",
                    step=step_no,
                    content=thought,
                )
            )

        if action == "final":
            final_answer = action_obj.get("final_answer", "").strip()

            with self.lock:
                self.finished = True

            self.save_session()
            self.finalize_session_memory()

            events.append(
                AgentEvent(
                    type="final",
                    step=step_no,
                    content=final_answer or "(empty final answer)",
                )
            )
            return events

        if action != "tool":
            raise InvalidModelOutputError(f"模型返回了未知 action: {action_obj}")

        tool_name = action_obj.get("tool_name", "")
        tool_args = action_obj.get("tool_args", {})

        if tool_name not in self.registry:
            raise InvalidModelOutputError(f"模型请求了未知工具: {tool_name}")

        command = render_tool_command(tool_name, tool_args)

        events.append(
            AgentEvent(
                type="tool_call",
                step=step_no,
                tool_name=tool_name,
                tool_args=tool_args,
                command=command,
            )
        )

        tool_feedback = self._execute_tool_or_permission_result(tool_name, tool_args)

        events.append(
            AgentEvent(
                type="tool_result",
                step=step_no,
                tool_name=tool_name,
                tool_args=tool_args,
                command=command,
                result=tool_feedback,
                status="success" if tool_feedback.get("ok") else "failed",
            )
        )

        with self.lock:
            self.messages.append(
                Message(
                    role="user",
                    content=build_tool_feedback_message(
                        json.dumps(tool_feedback, ensure_ascii=False, indent=2)
                    ),
                )
            )

        self.save_session()
        return events

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
        try:
            tool_result = tool.run(**tool_args)
        except Exception as e:
            raise ToolExecutionError(f"工具 {tool_name} 执行异常：{e}") from e

        if not hasattr(tool_result, "ok") or not hasattr(tool_result, "content"):
            raise ToolExecutionError(f"工具 {tool_name} 返回了非法结果对象。")

        return {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "ok": tool_result.ok,
            "content": tool_result.content,
            "meta": tool_result.meta or {},
        }

    def _maybe_request_permission(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        if tool_name != "run_command":
            return None

        command = str(tool_args.get("command", "")).strip()
        cwd = tool_args.get("cwd")
        if cwd is not None:
            cwd = str(cwd)

        decision = self.permissions.check_run_command(command, cwd)
        if decision.allowed:
            return None

        if decision.requires_user_approval:
            approved = self._ask_user_for_permission(
                command=command,
                cwd=cwd,
                requested_paths=decision.requested_paths,
                reason=decision.reason,
            )
            if approved:
                self.permissions.grant_write_accesses(decision.requested_paths)
                return None

        blocked_paths = "\n".join(f"- {path}" for path in decision.requested_paths)
        blocked_paths_text = blocked_paths if blocked_paths else "- (unknown)"

        return (
            "权限阻塞：检测到工作区外路径修改命令，当前入口已阻止执行。\n"
            f"command: {command or '(empty)'}\n"
            f"reason: {decision.reason}\n"
            "blocked_paths:\n"
            f"{blocked_paths_text}\n"
            "当前策略：只读命令默认允许；工作区内写入允许；工作区外写入需要用户授权。\n"
            "CLI 会直接询问是否授权；Web 可发送 /approve <path> 做永久授权。"
        )

    def _ask_user_for_permission(
        self,
        command: str,
        cwd: Optional[str],
        requested_paths: List[str],
        reason: str,
    ) -> bool:
        if self.permission_approval_handler is None:
            return False
        try:
            return bool(self.permission_approval_handler(command, cwd, PermissionDecision(
                allowed=False,
                reason=reason,
                requires_user_approval=True,
                requested_paths=requested_paths,
            )))
        except Exception:
            return False

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
