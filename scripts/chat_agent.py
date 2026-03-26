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
from agent.events import AgentEvent


def resolve_initial_task(cli_task: str) -> str:
    if cli_task:
        return cli_task
    return "请先探索当前工程，并准备协助我完成迁移相关工作。"


def summarize_tool_result(result: object, limit: int = 240) -> str:
    if not isinstance(result, dict):
        text = str(result or "").strip()
        return text if len(text) <= limit else text[:limit] + "..."

    content = result.get("content", "")
    if not isinstance(content, str):
        content = str(content)
    content = content.replace("\n", " ").strip()
    return content if len(content) <= limit else content[:limit] + "..."


def render_events(events: list[AgentEvent]) -> str:
    lines = []

    for event in events:
        if event.type == "thought" and event.content:
            lines.append(f"[thought] {event.content.strip()}")
            continue

        if event.type == "tool_call":
            command = (event.command or event.tool_name or "").strip()
            if command:
                lines.append(f"[tool] {command}")
            continue

        if event.type == "tool_result":
            tool_name = (event.tool_name or "").strip()
            status = (event.status or "").strip() or "unknown"
            summary = summarize_tool_result(event.result)
            prefix = f"[tool_result] {tool_name} ({status})".strip()
            lines.append(f"{prefix}: {summary}" if summary else prefix)
            continue

        if event.type == "final" and event.content:
            lines.append("[final]")
            lines.append(event.content.strip())
            continue

        if event.type == "error" and event.content:
            lines.append(f"[error] {event.content.strip()}")

    return "\n".join(lines).strip()


def run_agent_until_stop(agent: AgentLoop, max_steps: int) -> None:
    steps = 0

    while True:
        if agent.finished:
            print("\n[system] 当前 session 已完成。", flush=True)
            break

        if steps >= max_steps:
            agent.save_session()
            print("\n[system] 已达到本轮最大自动步数。", flush=True)
            break

        try:
            events = agent.step_once()
        except Exception as e:
            agent.save_session()
            print(f"\n[system] 自动执行失败：{e}", file=sys.stderr, flush=True)
            break

        rendered = render_events(events)
        print("\n===== AGENT =====", flush=True)
        if rendered:
            print(rendered, flush=True)
        else:
            print("(no visible events)", flush=True)

        steps += 1

        if any(event.type == "final" for event in events):
            break


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
    parser.add_argument("task", nargs="?", default="")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--max-steps", type=int, default=default_max_steps)
    parser.add_argument("--root", default=default_root)
    parser.add_argument("--chat-id", default=None, help="直接指定 chat_id")
    args = parser.parse_args()

    root_path = os.path.abspath(args.root)
    task_content = resolve_initial_task(args.task)

    chat_storage_path = config.get("agent.chat_storage_path", "./chats")
    session_storage_path = config.get("agent.session_storage_path", "./sessions")
    chat_memory = ChatMemory(chat_storage_path, session_storage_path)

    selected_chat_id = args.chat_id if args.chat_id else choose_chat(chat_memory)
    if selected_chat_id is None:
        selected_chat_id = chat_memory.create_chat()
        print(f"[system] 已创建新 chat: {selected_chat_id}")
    else:
        print(f"[system] 已选择恢复 chat: {selected_chat_id}")

    agent = AgentLoop(
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
        agent.start_session(
            task_content,
            load_existing=False,
            inject_current_chat_memory=True,
        )

        print(f"[system] 当前 chat_id: {agent.chat_id}")
        print(f"[system] 当前 session_id: {agent.session_id}")
        print("[system] 会话已创建，开始自动执行。")

        run_agent_until_stop(agent, agent.max_steps)

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
            new_task = input("请输入新的初始任务：").strip()
            if not new_task:
                new_task = "请探索当前工程，并准备协助我完成任务。"
            try:
                finalize_before_switch()
                agent = AgentLoop(
                    model=args.model,
                    max_steps=args.max_steps,
                    root=args.root,
                    chat_id=agent.chat_id,
                )
                agent.start_session(
                    new_task,
                    load_existing=False,
                    inject_current_chat_memory=True,
                )
                print("[system] 已重置当前 session，默认继续执行。")
                print(f"[system] 当前 chat_id: {agent.chat_id}")
                print(f"[system] 当前 session_id: {agent.session_id}")
                run_agent_until_stop(agent, agent.max_steps)
            except Exception as e:
                print(f"\n重置后运行失败：{e}", file=sys.stderr)
            continue

        if user_input == "/newchat":
            new_task = input("请输入新的初始任务：").strip()
            if not new_task:
                new_task = "请探索当前工程，并准备协助我完成任务。"
            try:
                finalize_before_switch()
                new_chat_id = chat_memory.create_chat()
                agent = AgentLoop(
                    model=args.model,
                    max_steps=args.max_steps,
                    root=args.root,
                    chat_id=new_chat_id,
                )
                agent.start_session(
                    new_task,
                    load_existing=False,
                    inject_current_chat_memory=True,
                )
                print(f"[system] 已创建新 chat: {agent.chat_id}")
                print(f"[system] 当前 session_id: {agent.session_id}")
                print("[system] 默认继续执行。")
                run_agent_until_stop(agent, agent.max_steps)
            except Exception as e:
                print(f"\n创建新 chat 失败：{e}", file=sys.stderr)
            continue

        try:
            agent.inject_user_message(user_input)
            agent.save_session()
            print("[system] 已接收消息，默认继续执行。")
            run_agent_until_stop(agent, agent.max_steps)
        except Exception as e:
            print(f"\n本轮执行失败：{e}", file=sys.stderr)
            print("session 仍然保留，你可以继续输入下一条消息。")


if __name__ == "__main__":
    main()
