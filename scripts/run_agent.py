#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from agent.loop import AgentLoop


def main() -> None:
    default_model = config.get("agent.model", "deepseek-chat")
    default_max_steps = config.get("scripts.run_agent.default_max_steps",
                                   config.get("agent.max_steps", 40))

    parser = argparse.ArgumentParser(description="Run migration agent")
    parser.add_argument("task", nargs="?", default="分析当前目录工程结构")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--max-steps", type=int, default=default_max_steps)
    args = parser.parse_args()

    try:
        agent = AgentLoop(model=args.model, max_steps=args.max_steps)
        agent.start_session(args.task, load_existing=False, inject_current_chat_memory=True)
        result = agent.run_until_stop(max_steps=args.max_steps)

        print("\n===== FINAL ANSWER =====")
        if result.final_answer:
            print(result.final_answer)
        elif result.stop_reason == "max_steps":
            print("本轮执行达到最大步数，尚未生成最终答复。")
        else:
            print(result.error_message or "本轮执行失败。")

        if result.stop_reason == "final":
            sys.exit(0)
        if result.stop_reason == "max_steps":
            sys.exit(2)
        sys.exit(1)

    except Exception as e:
        print(f"运行失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
