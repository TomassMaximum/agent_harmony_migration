import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

import config

from .custom_types import ChatRequest, Message
from .llm import create_llm
from .project_memory import (
    ProjectMemoryStore,
    ProjectMemoryValidationError,
    create_builder_job,
    create_default_coverage_status,
    create_project_overview,
    resolve_project_memory_path,
    utc_now_iso,
    validate_module_item,
    validate_unknown_item,
)


SYSTEM_PROMPT = """你是 Android -> HarmonyOS 迁移分析 orchestrator 的模块层分析 worker。

你的唯一任务是根据给定的 Android 工程快照，输出严格合法的 JSON，用于生成 project_memory 的模块层结果。

要求：
1. 只输出 JSON，不要输出 markdown。
2. 模块层必须追求当前层全量覆盖，而不是最小实现。
3. 必须覆盖提供的高信号 package refs 和 Gradle modules。
4. 所有结论都要引用给定 evidence ids。
5. 不确定项必须进入 unknowns，禁止伪确定。
6. 输出中的 unknown 分数范围必须是 0-100。
"""


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered or "item"


@dataclass
class PackageStat:
    ref: str
    relative_path: str
    file_count: int
    entrypoint_count: int
    sample_files: List[str]


@dataclass
class AndroidProjectSnapshot:
    source_project_path: str
    target_template_project_path: str
    gradle_modules: List[str]
    evidence_catalog: List[Dict[str, Any]]
    package_stats: List[PackageStat]
    manifest_activities: List[str]
    build_flavors: List[str]

    @property
    def evidence_ids(self) -> set:
        return {item["evidence_id"] for item in self.evidence_catalog}

    @property
    def package_refs(self) -> List[str]:
        return [item.ref for item in self.package_stats]

    @property
    def package_ref_set(self) -> set:
        return set(self.package_refs)

    @property
    def gradle_module_set(self) -> set:
        return set(self.gradle_modules)

    def high_signal_package_refs(self, min_file_count: int = 3) -> List[str]:
        refs: List[str] = []
        for item in self.package_stats:
            if item.file_count >= min_file_count or item.entrypoint_count > 0:
                refs.append(item.ref)
        return refs

    @property
    def package_stats_by_ref(self) -> Dict[str, PackageStat]:
        return {item.ref: item for item in self.package_stats}


@dataclass
class ReviewResult:
    accepted: bool
    issues: List[str]
    decision_score_over_threshold: List[str]


class Phase1ModuleAnalyzer:
    def __init__(
        self,
        source_project_path: str,
        target_template_project_path: str,
        output_project_memory_path: Optional[str] = None,
        llm_name: Optional[str] = None,
        retry_limit: int = 3,
        unknown_threshold: int = 60,
    ) -> None:
        self.source_project_path = os.path.abspath(source_project_path)
        self.target_template_project_path = os.path.abspath(target_template_project_path)
        self.output_project_memory_path = resolve_project_memory_path(
            self.target_template_project_path,
            output_project_memory_path,
        )
        self.llm_name = llm_name or config.get_current_llm_name()
        llm_config = config.get_llm_config(self.llm_name)
        self.model = llm_config["model"]
        self.llm = create_llm(llm_name=self.llm_name)
        self.retry_limit = max(1, int(retry_limit))
        self.unknown_threshold = int(unknown_threshold)
        self.store = ProjectMemoryStore(self.output_project_memory_path)

    def run(self) -> Dict[str, Any]:
        snapshot = inspect_android_project(self.source_project_path, self.target_template_project_path)
        builder_job = create_builder_job(
            source_project_path=self.source_project_path,
            target_template_project_path=self.target_template_project_path,
            output_project_memory_path=self.output_project_memory_path,
            llm_name=self.llm_name,
            unknown_threshold=self.unknown_threshold,
        )
        project_overview = create_project_overview(
            source_project_path=self.source_project_path,
            target_template_project_path=self.target_template_project_path,
            high_level_goal="完成阶段 1 模块层全量分析，产出可续跑的 project_memory。",
        )
        self.store.init_minimum_files(builder_job, project_overview)

        last_response: Optional[Dict[str, Any]] = None
        review: Optional[ReviewResult] = None
        attempts: List[Dict[str, Any]] = []

        for attempt_no in range(1, self.retry_limit + 1):
            prompt = build_module_analysis_prompt(
                snapshot=snapshot,
                unknown_threshold=self.unknown_threshold,
                previous_response=last_response,
                previous_issues=review.issues if review else None,
            )
            try:
                raw_content = self._call_llm(prompt)
                parsed = parse_json_response(raw_content)
                review = review_module_analysis(parsed, snapshot, self.unknown_threshold)
            except Exception as e:
                parsed = {
                    "error": str(e),
                }
                review = ReviewResult(
                    accepted=False,
                    issues=[f"attempt {attempt_no} 调用或解析失败: {e}"],
                    decision_score_over_threshold=[],
                )

            attempts.append(
                {
                    "attempt": attempt_no,
                    "accepted": review.accepted,
                    "issues": list(review.issues),
                    "response": parsed,
                    "recorded_at": utc_now_iso(),
                }
            )
            self.store.write_json(f"reviews/module_analysis_attempt_{attempt_no}.json", attempts[-1])

            if review.accepted:
                normalized = normalize_accepted_analysis(parsed, snapshot, self.unknown_threshold)
                self._persist(snapshot, builder_job, project_overview, normalized, review, attempt_no)
                return {
                    "accepted": True,
                    "attempt_count": attempt_no,
                    "project_memory_path": self.output_project_memory_path,
                    "review_issues": [],
                    "module_count": len(normalized["module_index"]),
                    "unknown_count": len(normalized["unknowns"]),
                }

            last_response = parsed

        assert review is not None
        self.store.write_json(
            "reviews/module_analysis_final_review.json",
            {
                "accepted": False,
                "issues": review.issues,
                "attempts": len(attempts),
                "updated_at": utc_now_iso(),
            },
        )
        return {
            "accepted": False,
            "attempt_count": len(attempts),
            "project_memory_path": self.output_project_memory_path,
            "review_issues": review.issues,
            "module_count": 0,
            "unknown_count": 0,
        }

    def _call_llm(self, prompt: str) -> str:
        response = self.llm.chat(
            ChatRequest(
                model=self.model,
                messages=[
                    Message(role="system", content=SYSTEM_PROMPT),
                    Message(role="user", content=prompt),
                ],
                temperature=0.2,
            )
        )
        return response.content.strip()

    def _persist(
        self,
        snapshot: AndroidProjectSnapshot,
        builder_job: Dict[str, Any],
        project_overview: Dict[str, Any],
        normalized: Dict[str, Any],
        review: ReviewResult,
        attempt_no: int,
    ) -> None:
        builder_job["status"] = "completed"
        builder_job["updated_at"] = utc_now_iso()

        project_overview["current_stage"] = "analyze_modules"
        project_overview["coverage_summary"]["modules_total"] = len(normalized["module_index"])
        project_overview["major_unknowns"] = [item["unknown_id"] for item in normalized["unknowns"]]
        project_overview["updated_at"] = utc_now_iso()

        coverage = create_default_coverage_status()
        coverage["module_analysis"] = "completed"
        coverage["cross_checks"]["module_to_page"] = "partial"
        coverage["updated_at"] = utc_now_iso()

        self.store.write_json("builder_job.json", builder_job)
        self.store.write_json("project_overview.json", project_overview)
        self.store.write_json("coverage_status.json", coverage)
        self.store.write_json("indexes/module_index.json", normalized["module_index"])
        self.store.write_json("indexes/evidence_index.json", normalized["evidence_index"])
        self.store.write_json("unknowns/queue.json", normalized["unknowns"])
        self.store.write_json("reviews/module_analysis_final_review.json", {
            "accepted": review.accepted,
            "issues": review.issues,
            "attempts": attempt_no,
            "updated_at": utc_now_iso(),
        })
        self.store.write_json("export_manifest.json", {
            "exports": [
                {
                    "name": "modules",
                    "path": "exports/modules.md",
                    "source_refs": [
                        "indexes/module_index.json",
                        "indexes/evidence_index.json",
                        "unknowns/queue.json",
                    ],
                }
            ],
            "updated_at": utc_now_iso(),
        })
        self.store.write_text("exports/modules.md", render_module_markdown(snapshot, normalized))


def inspect_android_project(source_project_path: str, target_template_project_path: str) -> AndroidProjectSnapshot:
    source_project_path = os.path.abspath(source_project_path)
    target_template_project_path = os.path.abspath(target_template_project_path)
    settings_path = _first_existing(
        os.path.join(source_project_path, "settings.gradle.kts"),
        os.path.join(source_project_path, "settings.gradle"),
    )
    if not settings_path:
        raise RuntimeError(f"未找到 settings.gradle(.kts): {source_project_path}")

    gradle_modules = _parse_gradle_modules(settings_path)
    build_flavors = _parse_build_flavors(os.path.join(source_project_path, "app", "build.gradle"))
    manifest_path = os.path.join(source_project_path, "app", "src", "main", "AndroidManifest.xml")
    manifest_activities = _parse_manifest_activities(manifest_path)
    package_stats = _collect_package_stats(source_project_path)
    evidence_catalog = _build_evidence_catalog(
        gradle_modules=gradle_modules,
        build_flavors=build_flavors,
        manifest_activities=manifest_activities,
        package_stats=package_stats,
    )

    return AndroidProjectSnapshot(
        source_project_path=source_project_path,
        target_template_project_path=target_template_project_path,
        gradle_modules=gradle_modules,
        evidence_catalog=evidence_catalog,
        package_stats=package_stats,
        manifest_activities=manifest_activities,
        build_flavors=build_flavors,
    )


def _first_existing(*paths: str) -> Optional[str]:
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def _parse_gradle_modules(settings_path: str) -> List[str]:
    text = _read_text(settings_path)
    return re.findall(r'include\("([^"]+)"\)', text)


def _parse_build_flavors(build_gradle_path: str) -> List[str]:
    if not os.path.exists(build_gradle_path):
        return []
    text = _read_text(build_gradle_path)
    lines = text.splitlines()
    in_block = False
    depth = 0
    flavors: List[str] = []

    for line in lines:
        if not in_block:
            if re.search(r"\bproductFlavors\s*\{", line):
                in_block = True
                depth = line.count("{") - line.count("}")
            continue

        if depth == 1:
            match = re.match(r"^\s*([A-Za-z0-9_]+)\s*\{$", line)
            if match:
                flavors.append(match.group(1))

        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break

    return sorted(dict.fromkeys(flavors))


def _parse_manifest_activities(manifest_path: str) -> List[str]:
    if not os.path.exists(manifest_path):
        return []
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    android_ns = "{http://schemas.android.com/apk/res/android}"
    activities: List[str] = []
    for tag_name in ("activity", "activity-alias"):
        for elem in root.findall(f".//{tag_name}"):
            name = elem.attrib.get(f"{android_ns}name")
            if name:
                activities.append(name)
    return activities


def _collect_package_stats(source_project_path: str) -> List[PackageStat]:
    app_src_path = os.path.join(source_project_path, "app", "src")
    if not os.path.isdir(app_src_path):
        return []

    package_dirs: Dict[str, Dict[str, Any]] = {}
    for source_set in sorted(os.listdir(app_src_path)):
        java_root = os.path.join(app_src_path, source_set, "java", "org", "wikipedia")
        if not os.path.isdir(java_root):
            continue

        root_key = "org.wikipedia.__root__"
        root_files = [
            name for name in os.listdir(java_root)
            if os.path.isfile(os.path.join(java_root, name)) and name.endswith((".kt", ".java"))
        ]
        if root_files:
            item = package_dirs.setdefault(root_key, {
                "relative_path": f"app/src/{source_set}/java/org/wikipedia",
                "file_count": 0,
                "entrypoint_count": 0,
                "sample_files": [],
            })
            item["file_count"] += len(root_files)
            item["entrypoint_count"] += sum(1 for name in root_files if _is_entrypoint_file(name))
            item["sample_files"].extend(root_files[:3])

        for child in sorted(os.listdir(java_root)):
            child_path = os.path.join(java_root, child)
            if not os.path.isdir(child_path):
                continue
            file_count, entrypoint_count, sample_files = _scan_code_dir(child_path)
            if file_count == 0:
                continue
            ref = f"org.wikipedia.{child}"
            item = package_dirs.setdefault(ref, {
                "relative_path": f"app/src/{source_set}/java/org/wikipedia/{child}",
                "file_count": 0,
                "entrypoint_count": 0,
                "sample_files": [],
            })
            item["file_count"] += file_count
            item["entrypoint_count"] += entrypoint_count
            for sample in sample_files:
                if len(item["sample_files"]) >= 3:
                    break
                if sample not in item["sample_files"]:
                    item["sample_files"].append(sample)

    results = [
        PackageStat(
            ref=ref,
            relative_path=meta["relative_path"],
            file_count=meta["file_count"],
            entrypoint_count=meta["entrypoint_count"],
            sample_files=meta["sample_files"][:3],
        )
        for ref, meta in package_dirs.items()
    ]
    results.sort(key=lambda item: (-item.file_count, item.ref))
    return results


def _scan_code_dir(root: str) -> Tuple[int, int, List[str]]:
    file_count = 0
    entrypoint_count = 0
    sample_files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in {"build", ".git", "__pycache__"}]
        for filename in filenames:
            if not filename.endswith((".kt", ".java")):
                continue
            file_count += 1
            if _is_entrypoint_file(filename):
                entrypoint_count += 1
            if len(sample_files) < 3:
                sample_files.append(os.path.relpath(os.path.join(dirpath, filename), root))
    return file_count, entrypoint_count, sample_files


def _is_entrypoint_file(filename: str) -> bool:
    return filename.endswith(("Activity.kt", "Activity.java", "Fragment.kt", "Fragment.java", "ViewModel.kt", "ViewModel.java"))


def _build_evidence_catalog(
    gradle_modules: Sequence[str],
    build_flavors: Sequence[str],
    manifest_activities: Sequence[str],
    package_stats: Sequence[PackageStat],
) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for gradle_module in gradle_modules:
        catalog.append({
            "evidence_id": f"ev_gradle_{_slugify(gradle_module)}",
            "source_type": "gradle_module",
            "source_path": "settings.gradle.kts",
            "locator": gradle_module,
            "summary": f"Gradle module {gradle_module}",
            "confidence": 100,
        })
    for flavor in build_flavors:
        catalog.append({
            "evidence_id": f"ev_flavor_{_slugify(flavor)}",
            "source_type": "build_flavor",
            "source_path": "app/build.gradle",
            "locator": flavor,
            "summary": f"Build flavor {flavor}",
            "confidence": 95,
        })
    for activity in manifest_activities:
        catalog.append({
            "evidence_id": f"ev_activity_{_slugify(activity)}",
            "source_type": "manifest_activity",
            "source_path": "app/src/main/AndroidManifest.xml",
            "locator": activity,
            "summary": f"Manifest activity {activity}",
            "confidence": 95,
        })
    for package_stat in package_stats:
        catalog.append({
            "evidence_id": f"ev_pkg_{_slugify(package_stat.ref)}",
            "source_type": "package_prefix",
            "source_path": package_stat.relative_path,
            "locator": package_stat.ref,
            "summary": (
                f"{package_stat.ref}: files={package_stat.file_count}, "
                f"entrypoints={package_stat.entrypoint_count}, samples={package_stat.sample_files}"
            ),
            "confidence": 90,
        })
    return catalog


def build_module_analysis_prompt(
    snapshot: AndroidProjectSnapshot,
    unknown_threshold: int,
    previous_response: Optional[Dict[str, Any]] = None,
    previous_issues: Optional[Sequence[str]] = None,
) -> str:
    high_signal_packages = snapshot.high_signal_package_refs()
    evidence_lines = []
    for item in snapshot.evidence_catalog:
        evidence_lines.append(
            f"- {item['evidence_id']} | {item['source_type']} | {item['locator']} | {item['summary']}"
        )

    package_lines = []
    for item in snapshot.package_stats:
        package_lines.append(
            f"- {item.ref} | files={item.file_count} | entrypoints={item.entrypoint_count} | path={item.relative_path}"
        )

    previous_block = ""
    if previous_response is not None and previous_issues:
        previous_block = (
            "\n上一次输出未通过本地审阅。请只做纠错，不要减少覆盖范围。\n"
            f"上一次审阅问题：\n- " + "\n- ".join(previous_issues) + "\n"
            f"上一次输出：\n{json.dumps(previous_response, ensure_ascii=False, indent=2)}\n"
        )

    schema = {
        "analysis_summary": "string",
        "module_index": [
            {
                "module_id": "string",
                "name": "string",
                "type": "business|infrastructure|shared|platform",
                "description": "string",
                "gradle_module_refs": ["string"],
                "package_refs": ["string"],
                "responsibilities": ["string"],
                "key_entrypoints": ["string"],
                "evidence_refs": ["string"],
                "unknown_refs": ["string"],
            }
        ],
        "unknowns": [
            {
                "unknown_id": "string",
                "title": "string",
                "description": "string",
                "category": "module_boundary|dependency|feature_coverage|platform_mapping|build_variant",
                "evidence_refs": ["string"],
                "candidate_options": ["string"],
                "recommended_option": "string",
                "uncertainty_score": 0,
                "severity_score": 0,
                "impact_scope": ["string"],
                "needs_user_confirmation": True,
            }
        ],
        "coverage": {
            "covered_package_refs": ["string"],
            "uncovered_package_refs": ["string"],
            "covered_gradle_module_refs": ["string"],
            "notes": ["string"],
        },
    }

    return f"""请基于以下 Android 工程快照输出模块层全量分析结果。

当前任务边界：
- 只做阶段 1：模块层分析
- 不做页面层和流程层
- 目标是形成可写入 project_memory 的 module_index / unknowns

项目：
- source_project_path: {snapshot.source_project_path}
- target_template_project_path: {snapshot.target_template_project_path}
- gradle_modules: {snapshot.gradle_modules}
- build_flavors: {snapshot.build_flavors}
- unknown_threshold: {unknown_threshold}

高信号 package refs，必须全部被 module_index 真正覆盖：
{chr(10).join(package_lines) if package_lines else "- (none)"}

这些 package refs 尤其不能漏：
{json.dumps(high_signal_packages[:40], ensure_ascii=False)}

Evidence catalog，引用时只能使用这些 evidence_id：
{chr(10).join(evidence_lines) if evidence_lines else "- (none)"}
{previous_block}
输出约束：
1. 只输出一个 JSON 对象。
2. module_index 至少拆成 4 个模块；如果你认为少于 4 个也合理，必须在 coverage.notes 中说明原因。
3. 每个高信号 package ref 必须真实出现在某个 module.package_refs 中，不能只写在 coverage.covered_package_refs。
4. coverage.uncovered_package_refs 对高信号 package refs 必须为空。
5. 每个 module 必须引用已有 evidence_id，严禁编造 evidence_id；如果没有更细粒度证据，优先引用 package evidence。
6. unknown 的 recommended_option 必须存在于 candidate_options。
7. 当 max(uncertainty_score, severity_score) >= {unknown_threshold} 时，needs_user_confirmation 必须为 true。
8. 如果包前缀是 org.wikipedia.__root__，表示 org.wikipedia 根目录下直接文件，也必须被归属到某个模块。
9. `infrastructure` 模块不应承接明显的用户功能包；如果某个 package ref 有 Activity/Fragment/ViewModel 等 entrypoints，除非它是明确测试支持包，否则优先归到 business/shared。

输出 schema 示例：
{json.dumps(schema, ensure_ascii=False, indent=2)}
"""


def parse_json_response(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"模块层分析输出不是合法 JSON: {e}\n原始输出:\n{text}") from e
    if not isinstance(data, dict):
        raise RuntimeError("模块层分析输出必须是 JSON 对象")
    return data


def review_module_analysis(data: Dict[str, Any], snapshot: AndroidProjectSnapshot, unknown_threshold: int) -> ReviewResult:
    issues: List[str] = []
    escalated_unknown_ids: List[str] = []
    allowed_infra_entrypoint_packages = {
        "org.wikipedia.__root__",
    }

    if not isinstance(data.get("analysis_summary"), str) or not data.get("analysis_summary", "").strip():
        issues.append("analysis_summary 缺失或为空")

    module_index = data.get("module_index")
    if not isinstance(module_index, list) or not module_index:
        issues.append("module_index 缺失或为空")
        return ReviewResult(False, issues, escalated_unknown_ids)

    unknowns = data.get("unknowns", [])
    if not isinstance(unknowns, list):
        issues.append("unknowns 必须是数组")
        unknowns = []

    coverage = data.get("coverage")
    if not isinstance(coverage, dict):
        issues.append("coverage 缺失或不是对象")
        coverage = {}

    unknown_ids = set()
    for item in unknowns:
        try:
            validate_unknown_item(item, snapshot.evidence_ids)
        except ProjectMemoryValidationError as e:
            issues.append(f"unknown 非法: {e}")
            continue
        unknown_id = item["unknown_id"]
        if unknown_id in unknown_ids:
            issues.append(f"unknown_id 重复: {unknown_id}")
        unknown_ids.add(unknown_id)

        decision_score = max(item["uncertainty_score"], item["severity_score"])
        if decision_score >= unknown_threshold and not item["needs_user_confirmation"]:
            issues.append(f"unknown {unknown_id} 超过阈值但未标记 needs_user_confirmation")
        if decision_score >= unknown_threshold:
            escalated_unknown_ids.append(unknown_id)

    module_ids = set()
    covered_packages = set()
    covered_gradle_modules = set()
    module_types = set()
    for item in module_index:
        try:
            validate_module_item(
                item=item,
                known_package_refs=snapshot.package_ref_set,
                known_gradle_refs=snapshot.gradle_module_set,
                known_evidence_ids=snapshot.evidence_ids,
                known_unknown_ids=unknown_ids,
            )
        except ProjectMemoryValidationError as e:
            issues.append(f"module 非法: {e}")
            continue
        module_id = item["module_id"]
        if module_id in module_ids:
            issues.append(f"module_id 重复: {module_id}")
        module_ids.add(module_id)
        module_types.add(item["type"])
        covered_packages.update(item["package_refs"])
        covered_gradle_modules.update(item["gradle_module_refs"])

        if item["type"] == "infrastructure":
            for package_ref in item["package_refs"]:
                stat = snapshot.package_stats_by_ref.get(package_ref)
                if not stat:
                    continue
                if stat.entrypoint_count > 0 and package_ref not in allowed_infra_entrypoint_packages:
                    issues.append(
                        f"infrastructure 模块包含疑似用户功能包: {package_ref} "
                        f"(entrypoints={stat.entrypoint_count})"
                    )

    if len(module_index) < 4 and len(snapshot.high_signal_package_refs()) >= 10:
        issues.append("模块拆分过粗：对于当前项目，module_index 少于 4 个模块")
    if "business" not in module_types:
        issues.append("module_index 缺少 business 类型模块")
    if not ({"shared", "infrastructure"} & module_types):
        issues.append("module_index 缺少 shared 或 infrastructure 类型模块")

    declared_covered_packages = coverage.get("covered_package_refs")
    if not isinstance(declared_covered_packages, list):
        issues.append("coverage.covered_package_refs 必须是数组")
        declared_covered_packages = []
    declared_uncovered_packages = coverage.get("uncovered_package_refs")
    if not isinstance(declared_uncovered_packages, list):
        issues.append("coverage.uncovered_package_refs 必须是数组")
        declared_uncovered_packages = []
    declared_covered_gradle = coverage.get("covered_gradle_module_refs")
    if not isinstance(declared_covered_gradle, list):
        issues.append("coverage.covered_gradle_module_refs 必须是数组")
        declared_covered_gradle = []

    for package_ref in declared_covered_packages + declared_uncovered_packages:
        if package_ref not in snapshot.package_ref_set:
            issues.append(f"coverage 中出现未知 package_ref: {package_ref}")
    for gradle_ref in declared_covered_gradle:
        if gradle_ref not in snapshot.gradle_module_set:
            issues.append(f"coverage 中出现未知 gradle module: {gradle_ref}")

    high_signal_packages = set(snapshot.high_signal_package_refs())
    missing_high_signal = sorted(high_signal_packages - covered_packages)
    if missing_high_signal:
        issues.append(f"高信号 package refs 未被模块覆盖: {missing_high_signal}")
    uncovered_high_signal = high_signal_packages.intersection(set(declared_uncovered_packages))
    if uncovered_high_signal:
        issues.append(f"coverage.uncovered_package_refs 不允许包含高信号包前缀: {sorted(uncovered_high_signal)}")

    missing_gradle = sorted(snapshot.gradle_module_set - covered_gradle_modules)
    if missing_gradle:
        issues.append(f"Gradle modules 未被模块覆盖: {missing_gradle}")

    root_package = "org.wikipedia.__root__"
    if root_package in snapshot.package_ref_set and root_package not in covered_packages:
        issues.append("org.wikipedia 根目录直接文件未被任何模块覆盖")

    return ReviewResult(
        accepted=not issues,
        issues=issues,
        decision_score_over_threshold=sorted(escalated_unknown_ids),
    )


def normalize_accepted_analysis(
    data: Dict[str, Any],
    snapshot: AndroidProjectSnapshot,
    unknown_threshold: int,
) -> Dict[str, Any]:
    module_index: List[Dict[str, Any]] = []
    unknowns: List[Dict[str, Any]] = []
    known_unknown_ids = set()

    for raw_unknown in data.get("unknowns", []):
        item = dict(raw_unknown)
        item.setdefault("status", "open")
        item.setdefault("recheck_count", 0)
        item["decision_score"] = max(item["uncertainty_score"], item["severity_score"])
        unknowns.append(item)
        known_unknown_ids.add(item["unknown_id"])

    for raw_module in data.get("module_index", []):
        item = dict(raw_module)
        item["status"] = "active"
        item["package_refs"] = sorted(dict.fromkeys(item.get("package_refs", [])))
        item["gradle_module_refs"] = sorted(dict.fromkeys(item.get("gradle_module_refs", [])))
        module_index.append(item)

    evidence_index = list(snapshot.evidence_catalog)
    return {
        "analysis_summary": data.get("analysis_summary", ""),
        "module_index": module_index,
        "unknowns": unknowns,
        "evidence_index": evidence_index,
        "coverage": data.get("coverage", {}),
    }


def render_module_markdown(snapshot: AndroidProjectSnapshot, normalized: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# 模块层分析")
    lines.append("")
    lines.append(f"- Source project: `{snapshot.source_project_path}`")
    lines.append(f"- Target template: `{snapshot.target_template_project_path}`")
    lines.append(f"- Gradle modules: {', '.join(snapshot.gradle_modules)}")
    lines.append(f"- Build flavors: {', '.join(snapshot.build_flavors)}")
    lines.append("")
    lines.append("## 总结")
    lines.append("")
    lines.append(normalized.get("analysis_summary", ""))
    lines.append("")
    lines.append("## 模块")
    lines.append("")
    for module in normalized["module_index"]:
        lines.append(f"### {module['name']}")
        lines.append("")
        lines.append(f"- id: `{module['module_id']}`")
        lines.append(f"- type: `{module['type']}`")
        lines.append(f"- description: {module['description']}")
        lines.append(f"- packages: {', '.join(module['package_refs'])}")
        lines.append(f"- gradle modules: {', '.join(module['gradle_module_refs']) or '(none)'}")
        lines.append(f"- unknown refs: {', '.join(module['unknown_refs']) or '(none)'}")
        lines.append("")
    lines.append("## Unknowns")
    lines.append("")
    if not normalized["unknowns"]:
        lines.append("- none")
    else:
        for item in normalized["unknowns"]:
            lines.append(
                f"- `{item['unknown_id']}`: {item['title']} "
                f"(decision_score={item['decision_score']}, "
                f"needs_user_confirmation={item['needs_user_confirmation']})"
            )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()
