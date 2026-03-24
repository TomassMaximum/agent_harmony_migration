#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import sys

# 让脚本可以直接从项目根目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent.llm import DeepSeekLLM


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepSeek chat client")
    parser.add_argument("prompt", nargs="?", default="你好，请确认连接成功。")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--system", default="You are a helpful assistant.")
    parser.add_argument("--raw", action="store_true", help="输出完整 JSON")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    args = parser.parse_args()

    try:
        llm = DeepSeekLLM()
        resp = llm.simple_chat(
            user_message=args.prompt,
            system_message=args.system,
            model=args.model,
        )

        if args.raw:
            print(json.dumps(resp.raw, ensure_ascii=False, indent=2))
        else:
            print(resp.content)

        if resp.usage:
            print("\n--- usage ---", file=sys.stderr)
            print(json.dumps(resp.usage, ensure_ascii=False, indent=2), file=sys.stderr)

    except Exception as e:
        print(f"运行失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()