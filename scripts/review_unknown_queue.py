#!/usr/bin/env python3

import argparse
import json
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

from agent.unknown_queue import (
    build_review_items,
    defer_review_item,
    format_review_items_text,
    load_confirmation_context,
    derive_batch_limit,
    derive_review_threshold,
    record_decision,
    resolve_confirmation_project_memory_path,
    set_confirmation_threshold,
)


def _add_common_path_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-template-project-path", default=None)
    parser.add_argument("--project-memory-path", default=None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review and resolve manual-confirmation unknown queue.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List the next review batch.")
    _add_common_path_args(list_parser)
    list_parser.add_argument("--threshold", type=int, default=None)
    list_parser.add_argument("--limit", type=int, default=None)
    list_parser.add_argument("--category", default=None)
    list_parser.add_argument("--status", action="append", default=None)
    list_parser.add_argument("--include-below-threshold", action="store_true")
    list_parser.add_argument("--format", choices=("text", "json"), default="text")

    decide_parser = subparsers.add_parser("decide", help="Confirm a review item.")
    _add_common_path_args(decide_parser)
    decide_parser.add_argument("--item-id", required=True)
    decide_parser.add_argument("--choice", required=True, help="Use 'recommended' or pass an explicit candidate option.")
    decide_parser.add_argument("--rationale", required=True)
    decide_parser.add_argument("--decision-source", default="user_cli")

    defer_parser = subparsers.add_parser("defer", help="Defer a review item.")
    _add_common_path_args(defer_parser)
    defer_parser.add_argument("--item-id", required=True)
    defer_parser.add_argument("--rationale", required=True)
    defer_parser.add_argument("--decision-source", default="user_cli")

    threshold_parser = subparsers.add_parser("set-threshold", help="Update unknown confirmation threshold.")
    _add_common_path_args(threshold_parser)
    threshold_parser.add_argument("--value", required=True, type=int)

    args = parser.parse_args()
    project_memory_path = resolve_confirmation_project_memory_path(
        target_template_project_path=getattr(args, "target_template_project_path", None),
        project_memory_path=getattr(args, "project_memory_path", None),
    )

    if args.command == "list":
        _store, builder_job, queue, _decisions = load_confirmation_context(project_memory_path)
        threshold = derive_review_threshold(builder_job, args.threshold)
        limit = derive_batch_limit(builder_job, args.limit)
        result = build_review_items(
            unknowns=queue,
            threshold=threshold,
            limit=limit,
            category=args.category,
            statuses=args.status,
            include_below_threshold=args.include_below_threshold,
        )
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_review_items_text(result), end="")
        return

    if args.command == "decide":
        result = record_decision(
            project_memory_path=project_memory_path,
            item_id=args.item_id,
            choice=args.choice,
            rationale=args.rationale,
            decision_source=args.decision_source,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "defer":
        result = defer_review_item(
            project_memory_path=project_memory_path,
            item_id=args.item_id,
            rationale=args.rationale,
            decision_source=args.decision_source,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "set-threshold":
        result = set_confirmation_threshold(project_memory_path, args.value)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
