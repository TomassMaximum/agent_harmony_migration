import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DEFAULT_PROJECT_MEMORY_RELPATH = os.path.join(".migration", "project_memory")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectMemoryValidationError(RuntimeError):
    pass


def derive_project_memory_path(target_template_project_path: str) -> str:
    target_root = os.path.abspath(target_template_project_path)
    return os.path.join(target_root, DEFAULT_PROJECT_MEMORY_RELPATH)


def resolve_project_memory_path(
    target_template_project_path: str,
    requested_project_memory_path: Optional[str] = None,
) -> str:
    if requested_project_memory_path and requested_project_memory_path.strip():
        return os.path.abspath(requested_project_memory_path)
    return derive_project_memory_path(target_template_project_path)


def _require_non_empty_string(data: Dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProjectMemoryValidationError(f"字段 {key} 必须是非空字符串")
    return value.strip()


def _require_dict(data: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ProjectMemoryValidationError(f"字段 {key} 必须是对象")
    return value


def _require_list(data: Dict[str, Any], key: str) -> List[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ProjectMemoryValidationError(f"字段 {key} 必须是数组")
    return value


def validate_builder_job(data: Dict[str, Any]) -> Dict[str, Any]:
    _require_non_empty_string(data, "job_id")
    _require_non_empty_string(data, "problem_type")
    _require_non_empty_string(data, "goal")
    _require_non_empty_string(data, "source_project_path")
    _require_non_empty_string(data, "target_template_project_path")
    _require_non_empty_string(data, "output_project_memory_path")

    status = _require_non_empty_string(data, "status")
    if status not in {"draft", "active", "paused_for_confirmation", "completed", "blocked"}:
        raise ProjectMemoryValidationError(f"builder_job.status 非法: {status}")

    llm_execution_profile = _require_dict(data, "llm_execution_profile")
    _require_non_empty_string(llm_execution_profile, "primary_model")
    _require_non_empty_string(llm_execution_profile, "review_model")

    confirmation_policy = _require_dict(data, "confirmation_policy")
    threshold = confirmation_policy.get("unknown_score_threshold")
    max_items = confirmation_policy.get("max_items_per_batch")
    if not isinstance(threshold, int) or threshold < 0 or threshold > 100:
        raise ProjectMemoryValidationError("confirmation_policy.unknown_score_threshold 必须是 0-100 整数")
    if not isinstance(max_items, int) or max_items <= 0:
        raise ProjectMemoryValidationError("confirmation_policy.max_items_per_batch 必须是正整数")

    _require_list(data, "acceptance_criteria")
    return data


def validate_project_overview(data: Dict[str, Any]) -> Dict[str, Any]:
    _require_non_empty_string(data, "project_name")
    _require_non_empty_string(data, "analysis_scope")
    _require_non_empty_string(data, "source_project_path")
    _require_non_empty_string(data, "target_template_project_path")
    _require_non_empty_string(data, "high_level_goal")
    _require_non_empty_string(data, "current_stage")

    coverage_summary = _require_dict(data, "coverage_summary")
    for key in ("modules_total", "pages_total", "flows_total", "features_total"):
        value = coverage_summary.get(key)
        if not isinstance(value, int) or value < 0:
            raise ProjectMemoryValidationError(f"coverage_summary.{key} 必须是非负整数")

    _require_list(data, "major_risks")
    _require_list(data, "major_unknowns")
    return data


def validate_coverage_status(data: Dict[str, Any]) -> Dict[str, Any]:
    phase_keys = (
        "module_analysis",
        "page_analysis",
        "flow_analysis",
        "feature_analysis",
        "implementation_skeleton",
        "test_skeleton",
    )
    for key in phase_keys:
        value = _require_non_empty_string(data, key)
        if value not in {"not_started", "in_progress", "completed"}:
            raise ProjectMemoryValidationError(f"{key} 状态非法: {value}")

    cross_checks = _require_dict(data, "cross_checks")
    for key in ("module_to_page", "page_to_flow", "flow_to_feature", "feature_to_file"):
        value = _require_non_empty_string(cross_checks, key)
        if value not in {"pass", "fail", "partial", "not_started"}:
            raise ProjectMemoryValidationError(f"cross_checks.{key} 状态非法: {value}")
    return data


def validate_unknown_item(item: Dict[str, Any], known_evidence_ids: Optional[set] = None) -> Dict[str, Any]:
    _require_non_empty_string(item, "unknown_id")
    _require_non_empty_string(item, "title")
    _require_non_empty_string(item, "description")
    _require_non_empty_string(item, "category")

    evidence_refs = _require_list(item, "evidence_refs")
    if known_evidence_ids is not None:
        for ref in evidence_refs:
            if ref not in known_evidence_ids:
                raise ProjectMemoryValidationError(f"unknown.evidence_refs 包含未知 evidence_id: {ref}")

    candidate_options = _require_list(item, "candidate_options")
    if not candidate_options:
        raise ProjectMemoryValidationError("unknown.candidate_options 不能为空")

    recommended = _require_non_empty_string(item, "recommended_option")
    if recommended not in candidate_options:
        raise ProjectMemoryValidationError("unknown.recommended_option 必须存在于 candidate_options")

    for score_key in ("uncertainty_score", "severity_score"):
        score = item.get(score_key)
        if not isinstance(score, int) or score < 0 or score > 100:
            raise ProjectMemoryValidationError(f"{score_key} 必须是 0-100 整数")

    impact_scope = _require_list(item, "impact_scope")
    if not impact_scope:
        raise ProjectMemoryValidationError("unknown.impact_scope 不能为空")

    needs_user_confirmation = item.get("needs_user_confirmation")
    if not isinstance(needs_user_confirmation, bool):
        raise ProjectMemoryValidationError("unknown.needs_user_confirmation 必须是布尔值")
    return item


def validate_module_item(
    item: Dict[str, Any],
    known_package_refs: set,
    known_gradle_refs: set,
    known_evidence_ids: set,
    known_unknown_ids: set,
) -> Dict[str, Any]:
    _require_non_empty_string(item, "module_id")
    _require_non_empty_string(item, "name")
    module_type = _require_non_empty_string(item, "type")
    if module_type not in {"business", "infrastructure", "shared", "platform"}:
        raise ProjectMemoryValidationError(f"module.type 非法: {module_type}")
    _require_non_empty_string(item, "description")

    gradle_refs = _require_list(item, "gradle_module_refs")
    for ref in gradle_refs:
        if ref not in known_gradle_refs:
            raise ProjectMemoryValidationError(f"module.gradle_module_refs 包含未知模块: {ref}")

    package_refs = _require_list(item, "package_refs")
    for ref in package_refs:
        if ref not in known_package_refs:
            raise ProjectMemoryValidationError(f"module.package_refs 包含未知包前缀: {ref}")

    if not gradle_refs and not package_refs:
        raise ProjectMemoryValidationError("module 至少要引用一个 gradle module 或 package")

    _require_list(item, "responsibilities")
    _require_list(item, "key_entrypoints")

    evidence_refs = _require_list(item, "evidence_refs")
    if not evidence_refs:
        raise ProjectMemoryValidationError("module.evidence_refs 不能为空")
    for ref in evidence_refs:
        if ref not in known_evidence_ids:
            raise ProjectMemoryValidationError(f"module.evidence_refs 包含未知 evidence_id: {ref}")

    unknown_refs = _require_list(item, "unknown_refs")
    for ref in unknown_refs:
        if ref not in known_unknown_ids:
            raise ProjectMemoryValidationError(f"module.unknown_refs 包含未知 unknown_id: {ref}")

    package_bindings = item.get("package_bindings")
    if package_bindings is not None:
        if not isinstance(package_bindings, list):
            raise ProjectMemoryValidationError("module.package_bindings 必须是数组")
        binding_refs = set()
        for binding in package_bindings:
            if not isinstance(binding, dict):
                raise ProjectMemoryValidationError("module.package_bindings 中每项必须是对象")
            package_ref = _require_non_empty_string(binding, "package_ref")
            gradle_module_ref = _require_non_empty_string(binding, "gradle_module_ref")
            source_sets = _require_list(binding, "source_sets")
            relative_paths = _require_list(binding, "relative_paths")
            if package_ref not in known_package_refs:
                raise ProjectMemoryValidationError(f"module.package_bindings 包含未知 package_ref: {package_ref}")
            if gradle_module_ref not in known_gradle_refs:
                raise ProjectMemoryValidationError(f"module.package_bindings 包含未知 gradle_module_ref: {gradle_module_ref}")
            if not source_sets:
                raise ProjectMemoryValidationError("module.package_bindings.source_sets 不能为空")
            if not relative_paths:
                raise ProjectMemoryValidationError("module.package_bindings.relative_paths 不能为空")
            if package_ref not in item["package_refs"]:
                raise ProjectMemoryValidationError("module.package_bindings.package_ref 必须存在于 module.package_refs")
            binding_refs.add(package_ref)

        missing_binding_refs = set(item["package_refs"]) - binding_refs
        if missing_binding_refs:
            raise ProjectMemoryValidationError(
                f"module.package_bindings 未覆盖全部 package_refs: {sorted(missing_binding_refs)}"
            )
    return item


@dataclass
class ProjectMemoryPaths:
    root: str
    indexes_dir: str
    unknowns_dir: str
    skeletons_dir: str
    exports_dir: str
    reviews_dir: str


class ProjectMemoryStore:
    def __init__(self, root: str) -> None:
        self.paths = ProjectMemoryPaths(
            root=os.path.abspath(root),
            indexes_dir=os.path.abspath(os.path.join(root, "indexes")),
            unknowns_dir=os.path.abspath(os.path.join(root, "unknowns")),
            skeletons_dir=os.path.abspath(os.path.join(root, "skeletons")),
            exports_dir=os.path.abspath(os.path.join(root, "exports")),
            reviews_dir=os.path.abspath(os.path.join(root, "reviews")),
        )

    def ensure_structure(self) -> None:
        for path in (
            self.paths.root,
            self.paths.indexes_dir,
            self.paths.unknowns_dir,
            self.paths.skeletons_dir,
            self.paths.exports_dir,
            self.paths.reviews_dir,
        ):
            os.makedirs(path, exist_ok=True)

    def write_json(self, relative_path: str, data: Any) -> str:
        self.ensure_structure()
        abs_path = os.path.join(self.paths.root, relative_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return abs_path

    def read_json(self, relative_path: str) -> Any:
        abs_path = os.path.join(self.paths.root, relative_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_text(self, relative_path: str, content: str) -> str:
        self.ensure_structure()
        abs_path = os.path.join(self.paths.root, relative_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return abs_path

    def init_minimum_files(self, builder_job: Dict[str, Any], project_overview: Dict[str, Any]) -> None:
        validate_builder_job(builder_job)
        validate_project_overview(project_overview)
        coverage_status = create_default_coverage_status()
        validate_coverage_status(coverage_status)

        self.write_json("builder_job.json", builder_job)
        self.write_json("project_overview.json", project_overview)
        self.write_json("coverage_status.json", coverage_status)
        self.write_json("export_manifest.json", {"exports": [], "updated_at": utc_now_iso()})
        self.write_json("indexes/module_index.json", [])
        self.write_json("indexes/page_index.json", [])
        self.write_json("indexes/flow_index.json", [])
        self.write_json("indexes/feature_index.json", [])
        self.write_json("indexes/file_index.json", [])
        self.write_json("indexes/evidence_index.json", [])
        self.write_json("unknowns/queue.json", [])
        self.write_json("unknowns/decisions.json", [])
        self.write_json("unknowns/final_gaps.json", [])
        self.write_json("skeletons/implementation_index.json", [])
        self.write_json("skeletons/test_index.json", [])


def create_default_coverage_status() -> Dict[str, Any]:
    return {
        "module_analysis": "not_started",
        "page_analysis": "not_started",
        "flow_analysis": "not_started",
        "feature_analysis": "not_started",
        "implementation_skeleton": "not_started",
        "test_skeleton": "not_started",
        "cross_checks": {
            "module_to_page": "not_started",
            "page_to_flow": "not_started",
            "flow_to_feature": "not_started",
            "feature_to_file": "not_started",
        },
        "updated_at": utc_now_iso(),
    }


def create_builder_job(
    source_project_path: str,
    target_template_project_path: str,
    output_project_memory_path: str,
    llm_name: str,
    unknown_threshold: int,
    max_items_per_batch: int = 10,
) -> Dict[str, Any]:
    return {
        "job_id": f"phase1-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "version": 1,
        "status": "active",
        "problem_type": "android_to_harmony_migration",
        "goal": "完成固定 Android 项目的阶段 1 模块层全量分析，并产出可续跑的 project_memory。",
        "source_project_path": os.path.abspath(source_project_path),
        "target_template_project_path": os.path.abspath(target_template_project_path),
        "output_project_memory_path": os.path.abspath(output_project_memory_path),
        "llm_execution_profile": {
            "primary_model": llm_name,
            "review_model": "local_deterministic_review",
        },
        "confirmation_policy": {
            "unknown_score_threshold": int(unknown_threshold),
            "max_items_per_batch": int(max_items_per_batch),
        },
        "acceptance_criteria": [
            "覆盖所有高信号包前缀",
            "覆盖所有 Gradle 模块",
            "unknown 结构合法且评分可筛选",
            "不允许关键包前缀无归属",
        ],
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }


def create_project_overview(
    source_project_path: str,
    target_template_project_path: str,
    high_level_goal: str,
) -> Dict[str, Any]:
    project_name = os.path.basename(os.path.abspath(source_project_path)) or "android-project"
    return {
        "project_name": project_name,
        "analysis_scope": "single_project_mvp",
        "source_project_path": os.path.abspath(source_project_path),
        "target_template_project_path": os.path.abspath(target_template_project_path),
        "high_level_goal": high_level_goal,
        "current_stage": "bootstrap_job",
        "coverage_summary": {
            "modules_total": 0,
            "pages_total": 0,
            "flows_total": 0,
            "features_total": 0,
        },
        "major_risks": [],
        "major_unknowns": [],
        "updated_at": utc_now_iso(),
    }
