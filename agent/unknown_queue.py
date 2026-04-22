import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .project_memory import ProjectMemoryStore, resolve_project_memory_path, utc_now_iso


ACTIVE_UNKNOWN_STATUSES = {"open", "needs_recheck", "in_review"}
HIGH_IMPACT_CATEGORIES = {"module_boundary", "build_variant", "entrypoint", "navigation"}


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    chars: List[str] = []
    for ch in lowered:
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("_")
    slug = "".join(chars)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "item"


def normalize_unknown_item(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    normalized.setdefault("status", "open")
    normalized.setdefault("recheck_count", 0)
    normalized.setdefault("needs_user_confirmation", False)
    normalized["decision_score"] = max(
        int(normalized.get("uncertainty_score", 0)),
        int(normalized.get("severity_score", 0)),
    )
    return normalized


def load_confirmation_context(project_memory_path: str) -> Tuple[ProjectMemoryStore, Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    store = ProjectMemoryStore(project_memory_path)
    builder_job = store.read_json("builder_job.json")
    queue = [normalize_unknown_item(item) for item in store.read_json("unknowns/queue.json")]
    decisions = store.read_json("unknowns/decisions.json")
    return store, builder_job, queue, decisions


def derive_review_threshold(builder_job: Dict[str, Any], override_threshold: Optional[int] = None) -> int:
    if override_threshold is not None:
        return int(override_threshold)
    policy = builder_job.get("confirmation_policy", {})
    return int(policy.get("unknown_score_threshold", 60))


def derive_batch_limit(builder_job: Dict[str, Any], override_limit: Optional[int] = None) -> int:
    if override_limit is not None:
        return max(1, int(override_limit))
    policy = builder_job.get("confirmation_policy", {})
    return max(1, int(policy.get("max_items_per_batch", 10)))


def requires_manual_review(item: Dict[str, Any], threshold: int) -> bool:
    if item.get("status") not in ACTIVE_UNKNOWN_STATUSES:
        return False
    if item.get("needs_user_confirmation"):
        return True
    if item["decision_score"] >= threshold:
        return True
    if item.get("category") in HIGH_IMPACT_CATEGORIES and int(item.get("severity_score", 0)) >= max(40, threshold - 20):
        return True
    impact_scope = set(item.get("impact_scope", []))
    if impact_scope.intersection({"module_index", "build_variant", "feature_coverage", "page_index"}):
        return int(item.get("severity_score", 0)) >= max(50, threshold - 10)
    return False


def filter_unknowns(
    unknowns: Sequence[Dict[str, Any]],
    threshold: int,
    category: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    include_below_threshold: bool = False,
) -> List[Dict[str, Any]]:
    normalized_statuses = set(statuses) if statuses else set(ACTIVE_UNKNOWN_STATUSES)
    filtered: List[Dict[str, Any]] = []
    for item in unknowns:
        normalized = normalize_unknown_item(item)
        if normalized["status"] not in normalized_statuses:
            continue
        if category and normalized.get("category") != category:
            continue
        if include_below_threshold:
            filtered.append(normalized)
            continue
        if requires_manual_review(normalized, threshold):
            filtered.append(normalized)
    return filtered


def _package_family_from_evidence(evidence_refs: Sequence[str]) -> str:
    if not evidence_refs:
        return "unknown"
    first = evidence_refs[0]
    if "/" not in first:
        return first
    folder = os.path.dirname(first)
    marker = "java/"
    if marker in folder:
        return folder.split(marker, 1)[1].replace("/", ".")
    return folder


def derive_review_cluster_key(item: Dict[str, Any]) -> Optional[str]:
    if item.get("category") != "page_mapping":
        return None
    candidate_options = item.get("candidate_options", [])
    if len(candidate_options) < 2:
        return None
    family = _package_family_from_evidence(item.get("evidence_refs", []))
    options_key = "|".join(sorted(candidate_options))
    return f"page_mapping|{family}|{options_key}"


def _build_review_item_from_bucket(cluster_key: str, items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    sorted_items = sorted(
        (normalize_unknown_item(item) for item in items),
        key=lambda item: (-item["decision_score"], item["unknown_id"]),
    )
    head = sorted_items[0]
    unknown_ids = [item["unknown_id"] for item in sorted_items]
    category = head["category"]
    evidence_refs = sorted({ref for item in sorted_items for ref in item.get("evidence_refs", [])})
    impact_scope = sorted({ref for item in sorted_items for ref in item.get("impact_scope", [])})
    candidate_options = sorted({ref for item in sorted_items for ref in item.get("candidate_options", [])})
    recommended_map = {item["unknown_id"]: item["recommended_option"] for item in sorted_items}

    if cluster_key.startswith("page_mapping|") and len(sorted_items) > 1:
        family = cluster_key.split("|", 2)[1]
        title = f"{family} 页面归属待确认 ({len(sorted_items)} 项)"
        summary = "同一包路径下的页面归属歧义，已按相同候选页面集合归并。"
        item_type = "cluster"
        review_item_id = f"cluster_{hashlib.sha1(cluster_key.encode('utf-8')).hexdigest()[:12]}"
    else:
        title = head["title"]
        summary = head["description"]
        item_type = "single"
        review_item_id = head["unknown_id"]

    blocking_reason = derive_blocking_reason(head, impact_scope)
    return {
        "review_item_id": review_item_id,
        "item_type": item_type,
        "title": title,
        "summary": summary,
        "category": category,
        "unknown_ids": unknown_ids,
        "item_count": len(sorted_items),
        "candidate_options": candidate_options,
        "recommended_option": head["recommended_option"] if len(set(recommended_map.values())) == 1 else "recommended_per_unknown",
        "recommended_options_by_unknown": recommended_map,
        "evidence_refs": evidence_refs,
        "impact_scope": impact_scope,
        "uncertainty_score": max(int(item["uncertainty_score"]) for item in sorted_items),
        "severity_score": max(int(item["severity_score"]) for item in sorted_items),
        "decision_score": max(int(item["decision_score"]) for item in sorted_items),
        "blocking_reason": blocking_reason,
        "cluster_key": cluster_key,
    }


def derive_blocking_reason(item: Dict[str, Any], impact_scope: Sequence[str]) -> str:
    category = item.get("category")
    if category == "module_boundary":
        return "模块边界判断错误会影响后续页面、功能点和工程骨架映射。"
    if category == "build_variant":
        return "构建变体判断错误会影响功能覆盖范围和目标工程可达性。"
    if category == "page_mapping":
        return "页面归属错误会影响后续流程分析和实现骨架落点。"
    if "build_variant" in impact_scope:
        return "该问题涉及构建与功能开关，错误决策会放大到后续阶段。"
    return "该问题仍可能阻塞后续阶段，需人工确认。"


def build_review_items(
    unknowns: Sequence[Dict[str, Any]],
    threshold: int,
    limit: int,
    category: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    include_below_threshold: bool = False,
) -> Dict[str, Any]:
    filtered = filter_unknowns(
        unknowns=unknowns,
        threshold=threshold,
        category=category,
        statuses=statuses,
        include_below_threshold=include_below_threshold,
    )
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for item in filtered:
        cluster_key = derive_review_cluster_key(item) or item["unknown_id"]
        buckets.setdefault(cluster_key, []).append(item)

    review_items = [
        _build_review_item_from_bucket(cluster_key, bucket)
        for cluster_key, bucket in buckets.items()
    ]
    review_items.sort(
        key=lambda item: (
            -int(item["decision_score"]),
            -int(item["severity_score"]),
            item["category"] not in HIGH_IMPACT_CATEGORIES,
            item["review_item_id"],
        )
    )

    return {
        "threshold": threshold,
        "total_unknowns": len(unknowns),
        "matched_unknowns": len(filtered),
        "returned_items": min(limit, len(review_items)),
        "review_items": review_items[:limit],
    }


def format_review_items_text(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"threshold={result['threshold']} matched_unknowns={result['matched_unknowns']} returned_items={result['returned_items']}")
    lines.append("")
    for idx, item in enumerate(result["review_items"], start=1):
        lines.append(f"{idx}. [{item['review_item_id']}] {item['title']}")
        lines.append(
            f"   category={item['category']} item_count={item['item_count']} "
            f"decision_score={item['decision_score']} severity={item['severity_score']} uncertainty={item['uncertainty_score']}"
        )
        lines.append(f"   blocking={item['blocking_reason']}")
        lines.append(f"   candidates={', '.join(item['candidate_options'])}")
        lines.append(f"   recommended={item['recommended_option']}")
        lines.append(f"   unknown_ids={', '.join(item['unknown_ids'])}")
        if item["evidence_refs"]:
            evidence_preview = ", ".join(item["evidence_refs"][:3])
            if len(item["evidence_refs"]) > 3:
                evidence_preview += ", ..."
            lines.append(f"   evidence={evidence_preview}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _find_review_item_by_id(
    review_items: Sequence[Dict[str, Any]],
    item_id: str,
) -> Dict[str, Any]:
    for item in review_items:
        if item["review_item_id"] == item_id:
            return item
    raise KeyError(f"未找到 review item: {item_id}")


def _find_unknown_by_id(unknowns: Sequence[Dict[str, Any]], unknown_id: str) -> Dict[str, Any]:
    for item in unknowns:
        if item["unknown_id"] == unknown_id:
            return item
    raise KeyError(f"未找到 unknown: {unknown_id}")


def record_decision(
    project_memory_path: str,
    item_id: str,
    choice: str,
    rationale: str,
    decision_source: str = "user_cli",
) -> Dict[str, Any]:
    store, builder_job, queue, decisions = load_confirmation_context(project_memory_path)
    threshold = derive_review_threshold(builder_job)
    review_items = build_review_items(
        unknowns=queue,
        threshold=threshold,
        limit=max(1000, len(queue)),
    )["review_items"]
    review_item = _find_review_item_by_id(review_items, item_id)

    updated_queue: List[Dict[str, Any]] = []
    created_records: List[Dict[str, Any]] = []
    target_unknown_ids = set(review_item["unknown_ids"])
    now = utc_now_iso()

    for item in queue:
        normalized = normalize_unknown_item(item)
        if normalized["unknown_id"] not in target_unknown_ids:
            updated_queue.append(normalized)
            continue

        if choice == "recommended":
            chosen_option = normalized["recommended_option"]
        else:
            chosen_option = choice
            if chosen_option not in normalized.get("candidate_options", []):
                raise RuntimeError(
                    f"unknown {normalized['unknown_id']} 不支持 chosen_option={chosen_option}"
                )

        decision_id = f"decision_{now.replace(':', '').replace('-', '')}_{_slugify(normalized['unknown_id'])}"
        normalized["status"] = "resolved"
        normalized["needs_user_confirmation"] = False
        normalized["chosen_option"] = chosen_option
        normalized["resolved_at"] = now
        normalized["decision_source"] = decision_source
        normalized["last_decision_id"] = decision_id
        updated_queue.append(normalized)

        created_records.append(
            {
                "decision_id": decision_id,
                "unknown_id": normalized["unknown_id"],
                "review_item_id": item_id,
                "decision_type": "confirmed",
                "chosen_option": chosen_option,
                "decision_source": decision_source,
                "rationale": rationale,
                "recorded_at": now,
            }
        )

    decisions.extend(created_records)
    store.write_json("unknowns/queue.json", updated_queue)
    store.write_json("unknowns/decisions.json", decisions)
    return {
        "project_memory_path": project_memory_path,
        "review_item_id": item_id,
        "updated_unknown_count": len(created_records),
        "decision_ids": [item["decision_id"] for item in created_records],
    }


def defer_review_item(
    project_memory_path: str,
    item_id: str,
    rationale: str,
    decision_source: str = "user_cli",
) -> Dict[str, Any]:
    store, builder_job, queue, decisions = load_confirmation_context(project_memory_path)
    threshold = derive_review_threshold(builder_job)
    review_items = build_review_items(
        unknowns=queue,
        threshold=threshold,
        limit=max(1000, len(queue)),
    )["review_items"]
    review_item = _find_review_item_by_id(review_items, item_id)

    updated_queue: List[Dict[str, Any]] = []
    created_records: List[Dict[str, Any]] = []
    target_unknown_ids = set(review_item["unknown_ids"])
    now = utc_now_iso()

    for item in queue:
        normalized = normalize_unknown_item(item)
        if normalized["unknown_id"] not in target_unknown_ids:
            updated_queue.append(normalized)
            continue

        decision_id = f"decision_{now.replace(':', '').replace('-', '')}_{_slugify(normalized['unknown_id'])}"
        normalized["status"] = "deferred"
        normalized["deferred_at"] = now
        normalized["decision_source"] = decision_source
        normalized["last_decision_id"] = decision_id
        updated_queue.append(normalized)

        created_records.append(
            {
                "decision_id": decision_id,
                "unknown_id": normalized["unknown_id"],
                "review_item_id": item_id,
                "decision_type": "deferred",
                "chosen_option": "",
                "decision_source": decision_source,
                "rationale": rationale,
                "recorded_at": now,
            }
        )

    decisions.extend(created_records)
    store.write_json("unknowns/queue.json", updated_queue)
    store.write_json("unknowns/decisions.json", decisions)
    return {
        "project_memory_path": project_memory_path,
        "review_item_id": item_id,
        "updated_unknown_count": len(created_records),
        "decision_ids": [item["decision_id"] for item in created_records],
    }


def set_confirmation_threshold(project_memory_path: str, value: int) -> Dict[str, Any]:
    store = ProjectMemoryStore(project_memory_path)
    builder_job = store.read_json("builder_job.json")
    builder_job.setdefault("confirmation_policy", {})
    builder_job["confirmation_policy"]["unknown_score_threshold"] = int(value)
    builder_job["updated_at"] = utc_now_iso()
    store.write_json("builder_job.json", builder_job)
    return {
        "project_memory_path": project_memory_path,
        "unknown_score_threshold": int(value),
    }


def resolve_confirmation_project_memory_path(
    target_template_project_path: Optional[str] = None,
    project_memory_path: Optional[str] = None,
) -> str:
    if not project_memory_path and not target_template_project_path:
        raise RuntimeError("需要提供 project_memory_path 或 target_template_project_path")
    return resolve_project_memory_path(
        target_template_project_path or project_memory_path or "",
        project_memory_path,
    )
