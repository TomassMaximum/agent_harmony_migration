#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

import config


def format_api_key_state(value: str) -> str:
    return "configured" if (value or "").strip() else "empty"


def print_current_llm() -> None:
    current = config.get_current_llm_config()
    print(current["name"])
    print(f"  provider: {current['provider']}")
    print(f"  model: {current['model']}")
    print(f"  base_url: {current.get('base_url') or '(default)'}")
    print(f"  api_key: {format_api_key_state(current.get('api_key', ''))}")
    print(f"  timeout: {current.get('timeout', 120)}")


def print_all_llms() -> None:
    current_name = config.get_current_llm_name()
    for name, entry in config.list_llms().items():
        marker = "*" if name == current_name else " "
        print(
            f"{marker} {name}"
            f"  provider={entry.get('provider', '')}"
            f"  model={entry.get('model', '')}"
            f"  api_key={format_api_key_state(entry.get('api_key', ''))}"
            f"  base_url={entry.get('base_url') or '(default)'}"
        )


def checkout_llm(name: str) -> None:
    selected = config.set_current_llm(name)
    print(
        f"已切换当前 LLM: {selected['name']} "
        f"(provider={selected['provider']}, model={selected['model']})"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage current LLM provider")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("which", help="打印当前正在使用的 LLM")
    subparsers.add_parser("ls", help="列出所有可用的 LLM")

    checkout_parser = subparsers.add_parser("checkout", help="切换当前正在使用的 LLM")
    checkout_parser.add_argument("name", help="要切换的 LLM 名称")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "which":
            print_current_llm()
            return 0

        if args.command == "ls":
            print_all_llms()
            return 0

        if args.command == "checkout":
            checkout_llm(args.name)
            return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
