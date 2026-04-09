#!/usr/bin/env python3

import argparse
import json
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

from agent.phase1_module_analysis import Phase1ModuleAnalyzer
from agent.project_memory import DEFAULT_PROJECT_MEMORY_RELPATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Run phase-1 module analysis for Android -> HarmonyOS migration.")
    parser.add_argument("--source-project-path", required=True)
    parser.add_argument("--target-template-project-path", required=True)
    parser.add_argument(
        "--output-project-memory-path",
        default=None,
        help=f"默认落到目标鸿蒙工程下的 {DEFAULT_PROJECT_MEMORY_RELPATH}",
    )
    parser.add_argument("--llm-name", default=None)
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument("--unknown-threshold", type=int, default=60)
    args = parser.parse_args()

    analyzer = Phase1ModuleAnalyzer(
        source_project_path=args.source_project_path,
        target_template_project_path=args.target_template_project_path,
        output_project_memory_path=args.output_project_memory_path,
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
