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
        result = agent.run(args.task)

        print("\n===== FINAL ANSWER =====")
        print(result)

    except Exception as e:
        print(f"运行失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
