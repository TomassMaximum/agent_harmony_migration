#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from agent.loop import AgentLoop
from agent.chat_memory import ChatMemory
from entry_common import (
    build_agent,
    render_cli_step_text,
    run_entry_turn,
    start_new_session,
)


def require_initial_task(cli_task: str) -> str:
    task = (cli_task or "").strip()
    if task:
        return task
    raise ValueError("必须显式提供初始任务。请使用: python3 scripts/chat_agent.py \"你的任务\"")


def prompt_required_task(prompt_text: str) -> str:
    task = input(prompt_text).strip()
    if not task:
        raise ValueError("必须显式输入初始任务。")
    return task


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

    choice = input("请输入要恢复的 chat 编号（直接回车表示新建 chat）：").strip()
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


def main() -> None:
    default_model = config.get("agent.model", "deepseek-chat")
    default_max_steps = config.get("agent.max_steps", 80)
    default_root = config.get("agent.root", ".")

    parser = argparse.ArgumentParser(description="Interactive agent session")
    parser.add_argument("task", help="初始任务")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--max-steps", type=int, default=default_max_steps)
    parser.add_argument("--root", default=default_root)
    parser.add_argument("--chat-id", default=None, help="直接指定 chat_id")
    args = parser.parse_args()

    root_path = os.path.abspath(args.root)
    task_content = require_initial_task(args.task)

    chat_storage_path = config.get("agent.chat_storage_path", "./chats")
    session_storage_path = config.get("agent.session_storage_path", "./sessions")
    chat_memory = ChatMemory(chat_storage_path, session_storage_path)

    selected_chat_id = args.chat_id if args.chat_id else choose_chat(chat_memory)
    if selected_chat_id is None:
        selected_chat_id = chat_memory.create_chat()
        print(f"[system] 已创建新 chat: {selected_chat_id}")
    else:
        print(f"[system] 已选择恢复 chat: {selected_chat_id}")

    agent = build_agent(
        model=args.model,
        max_steps=args.max_steps,
        root=args.root,
        chat_id=selected_chat_id,
    )

    def finalize_before_switch():
        try:
            agent.save_session()
            agent.finalize_session_memory()
        except Exception as e:
            print(f"[system] 结束前摘要更新失败：{e}", file=sys.stderr)

    print("===== START SESSION =====")
    print(f"workspace: {root_path}")
    print("输入 /exit 退出")
    print("输入 /save 手动保存并更新摘要")
    print("输入 /state 查看当前 session 状态")
    print("输入 /reset 重置当前 session（仍挂在当前 chat 下）")
    print("输入 /newchat 切换到一个新 chat")
    print("输入普通消息后，agent 会自动连续执行直到完成或达到步数上限")
    print()

    try:
        start_new_session(agent, task_content, inject_current_chat_memory=True)

        print(f"[system] 当前 chat_id: {agent.chat_id}")
        print(f"[system] 当前 session_id: {agent.session_id}")
        print("[system] 会话已创建，开始自动执行。")

        drive_cli_session_until_stop(agent, agent.max_steps)

    except Exception as e:
        print(f"\n初始化失败：{e}", file=sys.stderr)

    while True:
        try:
            user_input = input("\n===== YOU =====\n").strip()
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

        if user_input == "/reset":
            try:
                new_task = prompt_required_task("请输入新的初始任务：")
                finalize_before_switch()
                agent = build_agent(
                    model=args.model,
                    max_steps=args.max_steps,
                    root=args.root,
                    chat_id=agent.chat_id,
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
                new_task = prompt_required_task("请输入新的初始任务：")
                finalize_before_switch()
                new_chat_id = chat_memory.create_chat()
                agent = build_agent(
                    model=args.model,
                    max_steps=args.max_steps,
                    root=args.root,
                    chat_id=new_chat_id,
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
