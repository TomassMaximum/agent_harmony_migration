#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional
import shlex

from prompt_toolkit import PromptSession

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from agent.loop import AgentLoop
from agent.chat_memory import ChatMemory
from agent.permissions import PermissionDecision
from entry_common import (
    build_agent,
    render_cli_step_text,
    run_entry_turn,
    start_new_session,
)

SINGLE_LINE_SESSION = PromptSession()


def prompt_input(prompt_text: str) -> str:
    return SINGLE_LINE_SESSION.prompt(prompt_text)


def choose_editor() -> Optional[list]:
    """
    选择可用编辑器，返回 subprocess 可执行命令列表。
    优先级：
    1. VISUAL
    2. EDITOR
    3. code -w
    4. nano
    5. vim
    6. vi
    """
    env_visual = os.environ.get("VISUAL", "").strip()
    if env_visual:
        return shlex.split(env_visual)

    env_editor = os.environ.get("EDITOR", "").strip()
    if env_editor:
        return shlex.split(env_editor)

    if shutil.which("code"):
        return ["code", "-w"]

    for name in ("nano", "vim", "vi"):
        if shutil.which(name):
            return [name]

    return None


def open_external_editor(initial_text: str = "") -> str:
    """
    打开外部编辑器，返回编辑后的文本。
    若没有可用编辑器，抛出 RuntimeError。
    """
    editor_cmd = choose_editor()
    if not editor_cmd:
        raise RuntimeError(
            "未找到可用编辑器。请先设置 $EDITOR 或安装 code/nano/vim。"
        )

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".md", delete=False
        ) as f:
            temp_path = f.name
            if initial_text:
                f.write(initial_text)
            else:
                f.write(
                    "<!-- 在这里输入内容。保存并关闭编辑器后，将自动发送给 agent。 -->\n\n"
                )

        subprocess.run(editor_cmd + [temp_path], check=True)

        with open(temp_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("<!--") and stripped.endswith("-->"):
                continue
            lines.append(line)

        return "\n".join(lines).strip()

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def prompt_task_or_edit(prompt_text: str) -> str:
    """
    获取任务/消息输入：
    - 普通单行输入：直接返回
    - /edit：打开外部编辑器
    """
    while True:
        raw = prompt_input(prompt_text).strip()
        if raw == "/edit":
            try:
                content = open_external_editor()
            except Exception as e:
                print(f"[system] 打开外部编辑器失败：{e}", file=sys.stderr)
                continue
            if not content:
                print("[system] 编辑器内容为空，请重新输入。")
                continue
            return content

        if raw:
            return raw

        print("[system] 输入不能为空。你可以直接输入一行文字，或输入 /edit 打开编辑器。")


def prompt_permission_approval(command: str, cwd: Optional[str], decision: PermissionDecision) -> bool:
    print("\n===== PERMISSION REQUEST =====", flush=True)
    print("检测到工作区外写入命令，需要你的授权。", flush=True)
    print(f"command: {command or '(empty)'}", flush=True)
    if cwd:
        print(f"cwd: {cwd}", flush=True)
    print(f"reason: {decision.reason}", flush=True)
    print("paths:", flush=True)
    for path in decision.requested_paths:
        print(f"- {path}", flush=True)

    choice = prompt_input("是否永久授权以上路径给 agent？[y/N]: ").strip().lower()
    return choice in {"y", "yes"}


def drive_cli_session_until_stop(agent: AgentLoop, max_steps: int, user_message: Optional[str] = None) -> None:
    def handle_step(step_events) -> None:
        rendered = render_cli_step_text(step_events)
        if not rendered:
            return
        print("\n===== AGENT =====", flush=True)
        print(rendered, flush=True)

    result = run_entry_turn(
        agent,
        max_steps=max_steps,
        user_message=user_message,
        on_step=handle_step,
    )

    if result.stop_reason == "final":
        print("\n[system] 当前 session 已完成。", flush=True)
        return

    if result.stop_reason == "max_steps":
        print("\n[system] 已达到本轮最大自动步数。", flush=True)
        return

    if result.stop_reason == "permission_blocked":
        print(f"\n[system] 权限阻塞：{result.user_facing_text()}", file=sys.stderr, flush=True)
        return

    print(f"\n[system] 自动执行失败：{result.user_facing_text()}", file=sys.stderr, flush=True)


def choose_chat(chat_memory: ChatMemory) -> Optional[str]:
    recent = chat_memory.list_recent_chat_meta(limit=10)

    if not recent:
        print("[system] 当前没有历史 chat，将创建新 chat。")
        return None

    print("最近 10 个 chat：")
    for idx, item in enumerate(recent, start=1):
        title = item.get("title", "未命名会话")
        summary = item.get("summary", "")
        short_summary = summary[:80].replace("\n", " ")
        print(f"{idx}. {title}")
        if short_summary:
            print(f"   {short_summary}")

    choice = prompt_input("请输入要恢复的 chat 编号（直接回车表示新建 chat）：").strip()
    if not choice:
        return None

    try:
        num = int(choice)
        if 1 <= num <= len(recent):
            return recent[num - 1]["chat_id"]
    except Exception:
        pass

    print("[system] 输入无效，将创建新 chat。")
    return None


def build_initial_task() -> str:
    print("\n===== INITIAL TASK =====")
    print("请输入初始任务。")
    print("你可以：")
    print("- 直接输入一行文字后回车")
    print("- 输入 /edit 打开外部编辑器编写长内容")
    return prompt_task_or_edit("> ")


def build_user_message() -> str:
    print("\n===== YOU =====")
    print("请输入消息。")
    print("你可以：")
    print("- 直接输入一行文字后回车发送")
    print("- 输入 /edit 打开外部编辑器编写长内容")
    print("- 输入命令：/exit /save /state /permissions /approve <path> /reset /newchat")
    return prompt_task_or_edit("> ")


def main() -> None:
    current_llm = config.get_current_llm_config()
    default_max_steps = config.get(
        "scripts.chat_agent.default_max_steps",
        config.get("agent.max_steps", 80),
    )
    default_root = config.get("agent.root", ".")

    parser = argparse.ArgumentParser(description="Interactive agent session")
    parser.add_argument("--max-steps", type=int, default=default_max_steps)
    parser.add_argument("--root", default=default_root)
    parser.add_argument("--chat-id", default=None, help="直接指定 chat_id")
    args = parser.parse_args()

    root_path = os.path.abspath(args.root)

    chat_storage_path = config.get("agent.chat_storage_path", "./chats")
    session_storage_path = config.get("agent.session_storage_path", "./sessions")
    chat_memory = ChatMemory(chat_storage_path, session_storage_path)

    selected_chat_id = args.chat_id if args.chat_id else choose_chat(chat_memory)
    if selected_chat_id is None:
        selected_chat_id = chat_memory.create_chat()
        print(f"[system] 已创建新 chat: {selected_chat_id}")
    else:
        print(f"[system] 已选择恢复 chat: {selected_chat_id}")

    initial_task = build_initial_task()

    agent = build_agent(
        max_steps=args.max_steps,
        root=args.root,
        chat_id=selected_chat_id,
        permission_approval_handler=prompt_permission_approval,
    )

    def finalize_before_switch():
        try:
            agent.save_session()
            agent.finalize_session_memory()
        except Exception as e:
            print(f"[system] 结束前摘要更新失败：{e}", file=sys.stderr)

    print("===== START SESSION =====")
    print(f"workspace: {root_path}")
    print(
        f"llm: {current_llm['name']} "
        f"(provider={current_llm['provider']}, model={current_llm['model']})"
    )
    print("输入 /exit 退出")
    print("输入 /save 手动保存并更新摘要")
    print("输入 /state 查看当前 session 状态")
    print("输入 /permissions 查看当前永久授权路径")
    print("输入 /approve <path> 永久授权某个路径")
    print("输入 /reset 重置当前 session（仍挂在当前 chat 下）")
    print("输入 /newchat 切换到一个新 chat")
    print("输入 /edit 打开外部编辑器编写长文本")
    print()

    try:
        start_new_session(agent, initial_task, inject_current_chat_memory=True)

        print(f"[system] 当前 chat_id: {agent.chat_id}")
        print(f"[system] 当前 session_id: {agent.session_id}")
        print("[system] 会话已创建，开始自动执行。")

        drive_cli_session_until_stop(agent, agent.max_steps)

    except Exception as e:
        print(f"\n初始化失败：{e}", file=sys.stderr)

    while True:
        try:
            user_input = build_user_message().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n会话结束。")
            finalize_before_switch()
            break

        if not user_input:
            continue

        if user_input == "/exit":
            print("会话结束。")
            finalize_before_switch()
            break

        if user_input == "/save":
            try:
                agent.save_session()
                agent.finalize_session_memory()
                print("[system] 当前 session 已保存，摘要已更新。")
            except Exception as e:
                print(f"\n保存失败：{e}", file=sys.stderr)
            continue

        if user_input == "/state":
            print(f"chat_id: {agent.chat_id}")
            print(f"session_id: {agent.session_id}")
            print(f"当前消息数：{len(agent.messages)}")
            print(f"session_started：{agent.session_started}")
            print(f"finished：{agent.finished}")
            continue

        if user_input == "/permissions":
            print(agent.permissions.describe_allowed_write_roots())
            continue

        if user_input.startswith("/approve "):
            raw_path = user_input[len("/approve "):].strip()
            if not raw_path:
                print("[system] 用法：/approve <path>")
                continue
            agent.permissions.grant_write_access(raw_path)
            print(f"[system] 已永久授权路径：{raw_path}")
            print(agent.permissions.describe_allowed_write_roots())
            continue

        if user_input == "/reset":
            try:
                new_task = build_initial_task()
                finalize_before_switch()
                agent = build_agent(
                    max_steps=args.max_steps,
                    root=args.root,
                    chat_id=agent.chat_id,
                    permission_approval_handler=prompt_permission_approval,
                )
                start_new_session(agent, new_task, inject_current_chat_memory=True)
                print("[system] 已重置当前 session，默认继续执行。")
                print(f"[system] 当前 chat_id: {agent.chat_id}")
                print(f"[system] 当前 session_id: {agent.session_id}")
                drive_cli_session_until_stop(agent, agent.max_steps)
            except Exception as e:
                print(f"\n重置后运行失败：{e}", file=sys.stderr)
            continue

        if user_input == "/newchat":
            try:
                finalize_before_switch()
                new_chat_id = chat_memory.create_chat()
                new_task = build_initial_task()
                agent = build_agent(
                    max_steps=args.max_steps,
                    root=args.root,
                    chat_id=new_chat_id,
                    permission_approval_handler=prompt_permission_approval,
                )
                start_new_session(agent, new_task, inject_current_chat_memory=True)
                print(f"[system] 已创建新 chat: {agent.chat_id}")
                print(f"[system] 当前 session_id: {agent.session_id}")
                print("[system] 默认继续执行。")
                drive_cli_session_until_stop(agent, agent.max_steps)
            except Exception as e:
                print(f"\n创建新 chat 失败：{e}", file=sys.stderr)
            continue

        try:
            print("[system] 已接收消息，默认继续执行。")
            drive_cli_session_until_stop(agent, agent.max_steps, user_message=user_input)
        except Exception as e:
            print(f"\n本轮执行失败：{e}", file=sys.stderr)
            print("session 仍然保留，你可以继续输入下一条消息。")


if __name__ == "__main__":
    main()