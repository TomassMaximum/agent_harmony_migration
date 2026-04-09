#!/usr/bin/env python3

import argparse
import json
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

from agent.page_analysis import Stage2PageAnalyzer
from agent.project_memory import DEFAULT_PROJECT_MEMORY_RELPATH, resolve_project_memory_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run stage-2 page analysis for Android -> HarmonyOS migration.")
    parser.add_argument("--source-project-path", required=True)
    parser.add_argument("--target-template-project-path", default=None)
    parser.add_argument(
        "--project-memory-path",
        default=None,
        help=f"默认落到目标鸿蒙工程下的 {DEFAULT_PROJECT_MEMORY_RELPATH}",
    )
    parser.add_argument("--llm-name", default=None)
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument("--unknown-threshold", type=int, default=60)
    args = parser.parse_args()

    if not args.project_memory_path and not args.target_template_project_path:
        raise SystemExit("需要提供 --project-memory-path 或 --target-template-project-path")

    project_memory_path = resolve_project_memory_path(
        args.target_template_project_path or args.project_memory_path,
        args.project_memory_path,
    )

    analyzer = Stage2PageAnalyzer(
        source_project_path=args.source_project_path,
        project_memory_path=project_memory_path,
        llm_name=args.llm_name,
        retry_limit=args.retry_limit,
        unknown_threshold=args.unknown_threshold,
    )
    result = analyzer.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("accepted"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
