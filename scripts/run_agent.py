#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent.loop import AgentLoop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run migration agent")
    parser.add_argument("task", nargs="?", default="分析当前目录工程结构")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--max-steps", type=int, default=40)
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