import json
import os
import re
import threading
import uuid
from typing import Any, Dict, List, Optional

from .llm import DeepSeekLLM
from .memory import SessionMemory
from .permissions import PermissionManager
from .prompts import AGENT_SYSTEM_PROMPT
from .tool_registry import build_tool_registry, render_tool_descriptions
from .types import ChatRequest, Message
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


class AgentLoop:
    def __init__(self, model: str = None, max_steps: int = None, root: str = None, session_id: str = None) -> None:
        self.model = model if model is not None else config.get("agent.model", "deepseek-chat")
        self.max_steps = max_steps if max_steps is not None else config.get("agent.max_steps", 80)
        self.root = os.path.abspath(root if root is not None else config.get("agent.root", "."))
        self.llm = DeepSeekLLM()
        self.registry = build_tool_registry()
        self.permissions = PermissionManager(self.root)

        # 会话存储
        storage_path = config.get("agent.session_storage_path", "./sessions")
        self.memory = SessionMemory(storage_path)
        self.session_id = session_id if session_id else str(uuid.uuid4())

        self.messages: List[Message] = []
        self.session_started = False
        self.finished = False

        self.pause_requested = False
        self.lock = threading.RLock()

    def start_session(self, task: str, load_existing: bool = True) -> None:
        """
        启动新会话或恢复现有会话
        :param task: 任务描述
        :param load_existing: 如果为True且session_id已存在，则加载历史消息
        """
        with self.lock:
            if load_existing:
                # 尝试加载现有会话
                existing_messages = self.memory.load_session(self.session_id)
                if existing_messages:
                    self.messages = existing_messages
                    self.session_started = True
                    self.finished = False
                    self.pause_requested = False
                    print(f"[agent] 已恢复会话: {self.session_id}")
                    return

            # 新会话
            tools_text = render_tool_descriptions(self.registry)
            self.messages = [
                Message(role="system", content=AGENT_SYSTEM_PROMPT),
                Message(
                    role="user",
                    content=(
                        f"Workspace root:\n{self.root}\n\n"
                        f"Available tools:\n{tools_text}\n\n"
                        f"Initial task:\n{task}\n\n"
                        "Please explore step by step and help the user complete the task."
                    ),
                ),
            ]
            self.session_started = True
            self.finished = False
            self.pause_requested = False
            print(f"[agent] 新会话已启动: {self.session_id}")

    def reset_session(self) -> None:
        with self.lock:
            self.messages = []
            self.session_started = False
            self.finished = False
            self.pause_requested = False
            # 可选：删除存储的会话文件
            # self.memory.delete_session(self.session_id)

    def save_session(self) -> None:
        """保存当前会话到存储"""
        with self.lock:
            if not self.session_started:
                return
            self.memory.save_session(self.session_id, self.messages)
            print(f"[agent] 会话已保存: {self.session_id}")

    def load_session(self, session_id: str) -> bool:
        """加载指定会话ID的历史消息"""
        with self.lock:
            messages = self.memory.load_session(session_id)
            if messages:
                self.session_id = session_id
                self.messages = messages
                self.session_started = True
                self.finished = False
                self.pause_requested = False
                print(f"[agent] 已加载会话: {session_id}")
                return True
            else:
                print(f"[agent] 会话不存在: {session_id}")
                return False

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
        # 每次用户消息后自动保存会话
        self.save_session()
        return response

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
            # 最终答案后保存会话
            self.save_session()

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
                        "Based on this result, decide the next action."
                    ),
                )
            )
        # 工具执行后保存会话
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

        command = tool_args.get("command", "")
        cwd = tool_args.get("cwd")

        decision = self.permissions.check_run_command(command=command, cwd=cwd)
        if decision.allowed:
            return None

        if not decision.requires_user_approval:
            return (
                "命令未被执行，因为它不被允许。\n"
                f"command: {command}\n"
                f"cwd: {cwd}\n"
                f"reason: {decision.reason}"
            )

        approved = self._ask_user_for_permission(
            command=command,
            cwd=cwd,
            requested_paths=decision.requested_paths,
            reason=decision.reason,
        )

        if approved:
            return None

        return (
            "命令未被执行，因为用户未授予权限。\n"
            f"command: {command}\n"
            f"cwd: {cwd}\n"
            f"reason: {decision.reason}\n"
            "Please choose another approach if possible."
        )

    def _ask_user_for_permission(
        self,
        command: str,
        cwd: Optional[str],
        requested_paths: List[str],
        reason: str,
    ) -> bool:
        print("\n===== PERMISSION REQUIRED =====")
        print("Agent 想执行一个工作区外的潜在修改型命令。")
        print(f"cwd: {cwd}")
        print(f"command: {command}")
        print(f"reason: {reason}")

        if requested_paths:
            print("涉及路径：")
            for p in requested_paths:
                print(f"- {p}")

        print("\n可选操作：")
        print("y  : 仅本次允许")
        print("a  : 授权这些路径，后续也允许")
        print("n  : 拒绝")

        while True:
            try:
                answer = input("请输入 y / a / n: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n未收到授权输入，按拒绝处理。")
                return False

            if answer == "y":
                return True

            if answer == "a":
                for p in requested_paths:
                    self.permissions.grant_write_access(p)
                print("\n已授权以下路径的写操作：")
                print(self.permissions.describe_allowed_write_roots())
                return True

            if answer == "n":
                return False

            print("无效输入，请输入 y / a / n。")

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
