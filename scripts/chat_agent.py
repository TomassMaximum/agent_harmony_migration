#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from agent.loop import AgentLoop


def main() -> None:
    default_model = config.get("agent.model", "deepseek-chat")
    default_max_steps = config.get("agent.max_steps", 80)
    default_root = config.get("agent.root", ".")

    parser = argparse.ArgumentParser(description="Interactive agent session")
    parser.add_argument("task", nargs="?", default="请先探索当前工程，并准备协助我完成迁移相关工作。")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--max-steps", type=int, default=default_max_steps)
    parser.add_argument("--root", default=default_root)
    args = parser.parse_args()

    agent = AgentLoop(model=args.model, max_steps=args.max_steps, root=args.root)

    runner_thread = None
    runner_stop = threading.Event()

    def runner():
        nonlocal agent
        steps = 0
        try:
            while not runner_stop.is_set():
                if agent.is_pause_requested():
                    print("\n[system] 已暂停。", flush=True)
                    break

                if agent.finished:
                    print("\n[system] 当前 session 已完成。", flush=True)
                    break

                result = agent.step_once()
                print("\n===== AGENT =====", flush=True)
                print(result, flush=True)

                steps += 1
                if steps >= agent.max_steps:
                    print("\n[system] 已达到本轮最大自动步数。", flush=True)
                    break

                if agent.is_pause_requested():
                    print("\n[system] 已暂停。", flush=True)
                    break

                time.sleep(0.05)
        except Exception as e:
            print(f"\n[system] 自动执行失败：{e}", file=sys.stderr, flush=True)

    def start_runner():
        nonlocal runner_thread
        if runner_thread is not None and runner_thread.is_alive():
            print("[system] agent 已在运行中。")
            return
        runner_stop.clear()
        agent.clear_pause()
        runner_thread = threading.Thread(target=runner, daemon=True)
        runner_thread.start()

    print("===== START SESSION =====")
    print(f"workspace: {os.path.abspath(args.root)}")
    print("输入 /exit 退出")
    print("输入 /reset 重置上下文")
    print("输入 /pause 请求暂停")
    print("输入 /continue 后台继续执行")
    print("输入 /step 只执行一步")
    print("输入 /inject 你的补充信息")
    print("输入 /state 查看当前 session 状态\n")

    try:
        agent.start_session(args.task)
        print("会话已创建。输入 /step 或 /continue 开始。")
    except Exception as e:
        print(f"\n初始化失败：{e}", file=sys.stderr)

    while True:
        try:
            user_input = input("\n===== YOU =====\n").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n会话结束。")
            runner_stop.set()
            break

        if not user_input:
            continue

        if user_input == "/exit":
            print("会话结束。")
            runner_stop.set()
            break

        if user_input == "/pause":
            agent.request_pause()
            print("[system] 已发送暂停请求。会在当前 step 完成后暂停。")
            continue

        if user_input == "/continue":
            start_runner()
            continue

        if user_input == "/step":
            if runner_thread is not None and runner_thread.is_alive():
                print("[system] agent 正在自动运行中，请先 /pause。")
                continue
            try:
                result = agent.step_once()
                print("\n===== AGENT =====")
                print(result)
            except Exception as e:
                print(f"\n单步执行失败：{e}", file=sys.stderr)
            continue

        if user_input.startswith("/inject "):
            injected = user_input[len("/inject "):].strip()
            if not injected:
                print("补充信息为空。")
                continue
            try:
                agent.inject_user_message(injected)
                print("[system] 已注入补充信息。可 /step 或 /continue。")
            except Exception as e:
                print(f"\n注入失败：{e}", file=sys.stderr)
            continue

        if user_input == "/state":
            print(f"当前消息数：{len(agent.messages)}")
            print(f"session_started：{agent.session_started}")
            print(f"finished：{agent.finished}")
            print(f"pause_requested：{agent.is_pause_requested()}")
            print(f"runner_alive：{runner_thread.is_alive() if runner_thread else False}")
            continue

        if user_input == "/reset":
            if runner_thread is not None and runner_thread.is_alive():
                print("[system] 请先 /pause，等待自动执行停下后再 /reset。")
                continue
            new_task = input("请输入新的初始任务：").strip()
            if not new_task:
                new_task = "请探索当前工程，并准备协助我完成任务。"
            try:
                agent.reset_session()
                agent.start_session(new_task)
                print("[system] 已重置 session。输入 /step 或 /continue 开始。")
            except Exception as e:
                print(f"\n重置后运行失败：{e}", file=sys.stderr)
            continue

        if runner_thread is not None and runner_thread.is_alive():
            print("[system] agent 正在自动运行。先 /pause，再补充普通消息，或使用 /inject。")
            continue

        try:
            result = agent.send_user_message(user_input)
            print("\n===== AGENT =====")
            print(result)
        except Exception as e:
            print(f"\n本轮执行失败：{e}", file=sys.stderr)
            print("session 仍然保留，你可以继续输入下一条消息。")


if __name__ == "__main__":
    main()
