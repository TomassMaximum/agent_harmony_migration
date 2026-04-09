import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from xml.etree import ElementTree as ET

import config

from .custom_types import ChatRequest, Message
from .llm import create_llm
from .phase1_module_analysis import parse_json_response, _parse_gradle_modules, _first_existing, _slugify
from .project_memory import (
    ProjectMemoryStore,
    ProjectMemoryValidationError,
    utc_now_iso,
    validate_unknown_item,
)


SYSTEM_PROMPT = """你是 Android -> HarmonyOS 迁移分析 orchestrator 的页面层分析 worker。

你的唯一任务是根据给定的工程快照和已有 module_index，输出严格合法的 JSON，用于生成 page_index。

要求：
1. 只输出 JSON。
2. 页面层必须覆盖所有 manifest activity，以及所有高信号 UI 组件。
3. 如果某个 UI 组件不是独立页面，必须放进 supporting_component_refs 或 ignored_components，并给出理由。
4. 不允许伪覆盖：只有真实写进 page_index 或 ignored_components 的组件，才算覆盖。
5. 不确定项必须进入 unknowns。
"""


@dataclass
class UIComponent:
    component_ref: str
    component_type: str
    symbol_name: str
    fqcn: str
    package_ref: str
    source_path: str
    source_relpath: str
    source_set: str
    module_ids: List[str]
    manifest_declared: bool = False


@dataclass
class PageAnalysisSnapshot:
    source_project_path: str
    project_memory_path: str
    module_index: List[Dict[str, Any]]
    components: List[UIComponent]
    manifest_activity_refs: List[str]
    module_ids: List[str]

    @property
    def component_ref_set(self) -> Set[str]:
        return {item.component_ref for item in self.components}

    @property
    def component_by_ref(self) -> Dict[str, UIComponent]:
        return {item.component_ref: item for item in self.components}


@dataclass
class PageReviewResult:
    accepted: bool
    issues: List[str]


class Stage2PageAnalyzer:
    def __init__(
        self,
        source_project_path: str,
        project_memory_path: str,
        llm_name: Optional[str] = None,
        retry_limit: int = 3,
        unknown_threshold: int = 60,
    ) -> None:
        self.source_project_path = os.path.abspath(source_project_path)
        self.project_memory_path = os.path.abspath(project_memory_path)
        self.store = ProjectMemoryStore(self.project_memory_path)
        self.llm_name = llm_name or config.get_current_llm_name()
        llm_config = config.get_llm_config(self.llm_name)
        self.model = llm_config["model"]
        self.llm = create_llm(llm_name=self.llm_name)
        self.retry_limit = max(1, int(retry_limit))
        self.unknown_threshold = int(unknown_threshold)

    def run(self) -> Dict[str, Any]:
        snapshot = inspect_page_analysis_snapshot(self.source_project_path, self.project_memory_path)
        upgraded_module_index = enrich_module_index_with_package_bindings(
            source_project_path=self.source_project_path,
            module_index=snapshot.module_index,
        )
        self.store.write_json("indexes/module_index.json", upgraded_module_index)
        snapshot = inspect_page_analysis_snapshot(self.source_project_path, self.project_memory_path)

        if len(snapshot.manifest_activity_refs) > 25:
            return self._run_chunked(snapshot)

        return self._run_one_shot(snapshot)

    def _run_one_shot(self, snapshot: PageAnalysisSnapshot) -> Dict[str, Any]:
        last_response: Optional[Dict[str, Any]] = None
        review: Optional[PageReviewResult] = None
        for attempt_no in range(1, self.retry_limit + 1):
            prompt = build_page_analysis_prompt(
                snapshot=snapshot,
                unknown_threshold=self.unknown_threshold,
                previous_response=last_response,
                previous_issues=review.issues if review else None,
            )
            try:
                raw = self.llm.chat(
                    ChatRequest(
                        model=self.model,
                        messages=[
                            Message(role="system", content=SYSTEM_PROMPT),
                            Message(role="user", content=prompt),
                        ],
                        temperature=0.2,
                    )
                ).content.strip()
                parsed = parse_json_response(raw)
                review = review_page_analysis(parsed, snapshot, self.unknown_threshold)
            except Exception as e:
                parsed = {"error": str(e)}
                review = PageReviewResult(
                    accepted=False,
                    issues=[f"attempt {attempt_no} 调用或解析失败: {e}"],
                )

            self.store.write_json(
                f"reviews/page_analysis_attempt_{attempt_no}.json",
                {
                    "attempt": attempt_no,
                    "accepted": review.accepted,
                    "issues": review.issues,
                    "response": parsed,
                    "recorded_at": utc_now_iso(),
                },
            )
            if review.accepted:
                normalized = normalize_page_analysis(parsed)
                self._persist(snapshot, normalized, attempt_no)
                return {
                    "accepted": True,
                    "attempt_count": attempt_no,
                    "project_memory_path": self.project_memory_path,
                    "page_count": len(normalized["page_index"]),
                    "unknown_count": len(normalized["unknowns"]),
                }
            last_response = parsed

        assert review is not None
        self.store.write_json(
            "reviews/page_analysis_final_review.json",
            {
                "accepted": False,
                "issues": review.issues,
                "attempts": self.retry_limit,
                "updated_at": utc_now_iso(),
            },
        )
        return {
            "accepted": False,
            "attempt_count": self.retry_limit,
            "project_memory_path": self.project_memory_path,
            "page_count": 0,
            "unknown_count": 0,
            "review_issues": review.issues,
        }

    def _run_chunked(self, snapshot: PageAnalysisSnapshot) -> Dict[str, Any]:
        activity_refs = list(snapshot.manifest_activity_refs)
        merged_pages: List[Dict[str, Any]] = []
        merged_unknowns: List[Dict[str, Any]] = []
        summaries: List[str] = []
        total_attempts = 0

        for chunk_no, chunk_refs in enumerate(chunked(activity_refs, 20), start=1):
            last_response: Optional[Dict[str, Any]] = None
            review: Optional[PageReviewResult] = None
            chunk_result: Optional[Dict[str, Any]] = None
            for attempt_no in range(1, self.retry_limit + 1):
                total_attempts += 1
                prompt = build_activity_chunk_prompt(
                    snapshot=snapshot,
                    activity_refs=chunk_refs,
                    unknown_threshold=self.unknown_threshold,
                    previous_response=last_response,
                    previous_issues=review.issues if review else None,
                )
                try:
                    raw = self.llm.chat(
                        ChatRequest(
                            model=self.model,
                            messages=[
                                Message(role="system", content=SYSTEM_PROMPT),
                                Message(role="user", content=prompt),
                            ],
                            temperature=0.2,
                        )
                    ).content.strip()
                    parsed = parse_json_response(raw)
                    review = review_activity_chunk(parsed, chunk_refs, snapshot.module_ids, self.unknown_threshold)
                except Exception as e:
                    parsed = {"error": str(e)}
                    review = PageReviewResult(
                        accepted=False,
                        issues=[f"chunk {chunk_no} attempt {attempt_no} 调用或解析失败: {e}"],
                    )

                self.store.write_json(
                    f"reviews/page_activity_chunk_{chunk_no}_attempt_{attempt_no}.json",
                    {
                        "chunk": chunk_no,
                        "attempt": attempt_no,
                        "activity_refs": chunk_refs,
                        "accepted": review.accepted,
                        "issues": review.issues,
                        "response": parsed,
                        "recorded_at": utc_now_iso(),
                    },
                )
                if review.accepted:
                    chunk_result = normalize_activity_chunk_response(parsed)
                    break
                last_response = parsed

            if chunk_result is None:
                assert review is not None
                self.store.write_json(
                    "reviews/page_analysis_final_review.json",
                    {
                        "accepted": False,
                        "issues": review.issues,
                        "attempts": total_attempts,
                        "updated_at": utc_now_iso(),
                    },
                )
                return {
                    "accepted": False,
                    "attempt_count": total_attempts,
                    "project_memory_path": self.project_memory_path,
                    "page_count": 0,
                    "unknown_count": 0,
                    "review_issues": review.issues,
                }

            summaries.append(chunk_result["analysis_summary"])
            merged_pages.extend(chunk_result["page_index"])
            merged_unknowns.extend(chunk_result["unknowns"])

        normalized = {
            "analysis_summary": "\n".join(item for item in summaries if item.strip()),
            "page_index": merged_pages,
            "ignored_components": [],
            "unknowns": merge_unknowns([], merged_unknowns),
            "coverage": {},
        }
        normalized = augment_page_analysis_with_support_components(snapshot, normalized, self.unknown_threshold)
        final_review = review_page_analysis(normalized, snapshot, self.unknown_threshold)
        if not final_review.accepted:
            self.store.write_json(
                "reviews/page_analysis_final_review.json",
                {
                    "accepted": False,
                    "issues": final_review.issues,
                    "attempts": total_attempts,
                    "updated_at": utc_now_iso(),
                },
            )
            return {
                "accepted": False,
                "attempt_count": total_attempts,
                "project_memory_path": self.project_memory_path,
                "page_count": len(normalized["page_index"]),
                "unknown_count": len(normalized["unknowns"]),
                "review_issues": final_review.issues,
            }

        self._persist(snapshot, normalized, total_attempts)
        return {
            "accepted": True,
            "attempt_count": total_attempts,
            "project_memory_path": self.project_memory_path,
            "page_count": len(normalized["page_index"]),
            "unknown_count": len(normalized["unknowns"]),
        }

    def _persist(self, snapshot: PageAnalysisSnapshot, normalized: Dict[str, Any], attempt_no: int) -> None:
        coverage = self.store.read_json("coverage_status.json")
        coverage["page_analysis"] = "completed"
        coverage["cross_checks"]["module_to_page"] = "pass"
        coverage["updated_at"] = utc_now_iso()
        self.store.write_json("coverage_status.json", coverage)

        self.store.write_json("indexes/page_index.json", normalized["page_index"])

        unknown_queue = self.store.read_json("unknowns/queue.json")
        merged_unknowns = merge_unknowns(unknown_queue, normalized["unknowns"])
        self.store.write_json("unknowns/queue.json", merged_unknowns)

        export_manifest = self.store.read_json("export_manifest.json")
        exports = export_manifest.get("exports", [])
        exports = [item for item in exports if item.get("name") != "pages"]
        exports.append(
            {
                "name": "pages",
                "path": "exports/pages.md",
                "source_refs": [
                    "indexes/page_index.json",
                    "indexes/module_index.json",
                    "unknowns/queue.json",
                ],
            }
        )
        export_manifest["exports"] = exports
        export_manifest["updated_at"] = utc_now_iso()
        self.store.write_json("export_manifest.json", export_manifest)

        self.store.write_json(
            "reviews/page_analysis_final_review.json",
            {
                "accepted": True,
                "issues": [],
                "attempts": attempt_no,
                "updated_at": utc_now_iso(),
            },
        )
        self.store.write_text("exports/pages.md", render_pages_markdown(snapshot, normalized))


def inspect_page_analysis_snapshot(source_project_path: str, project_memory_path: str) -> PageAnalysisSnapshot:
    store = ProjectMemoryStore(project_memory_path)
    module_index = store.read_json("indexes/module_index.json")
    module_ids = [item["module_id"] for item in module_index if isinstance(item, dict) and item.get("module_id")]
    module_package_map = build_module_package_map(module_index)
    components, manifest_activity_refs = collect_ui_components(source_project_path, module_package_map)
    return PageAnalysisSnapshot(
        source_project_path=os.path.abspath(source_project_path),
        project_memory_path=os.path.abspath(project_memory_path),
        module_index=module_index,
        components=components,
        manifest_activity_refs=manifest_activity_refs,
        module_ids=module_ids,
    )


def build_module_package_map(module_index: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for item in module_index:
        module_id = item.get("module_id")
        package_refs = item.get("package_refs", [])
        if not isinstance(module_id, str) or not isinstance(package_refs, list):
            continue
        for package_ref in package_refs:
            mapping.setdefault(package_ref, []).append(module_id)
    return mapping


def resolve_module_ids_for_package(package_ref: str, module_package_map: Dict[str, List[str]]) -> List[str]:
    exact = module_package_map.get(package_ref)
    if exact:
        return sorted(dict.fromkeys(exact))

    best_prefix_len = -1
    matched_ids: List[str] = []
    for known_package_ref, module_ids in module_package_map.items():
        if known_package_ref == "org.wikipedia.__root__":
            continue
        if package_ref.startswith(f"{known_package_ref}."):
            prefix_len = len(known_package_ref)
            if prefix_len > best_prefix_len:
                best_prefix_len = prefix_len
                matched_ids = list(module_ids)
            elif prefix_len == best_prefix_len:
                matched_ids.extend(module_ids)

    if matched_ids:
        return sorted(dict.fromkeys(matched_ids))

    root_ids = module_package_map.get("org.wikipedia.__root__", [])
    if root_ids and package_ref.startswith("org.wikipedia"):
        return sorted(dict.fromkeys(root_ids))
    return []


def enrich_module_index_with_package_bindings(source_project_path: str, module_index: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    settings_path = _first_existing(
        os.path.join(source_project_path, "settings.gradle.kts"),
        os.path.join(source_project_path, "settings.gradle"),
    )
    gradle_modules = _parse_gradle_modules(settings_path) if settings_path else [":app"]

    upgraded: List[Dict[str, Any]] = []
    for item in module_index:
        module_copy = dict(item)
        bindings: List[Dict[str, Any]] = []
        seen_keys: Set[Tuple[str, str]] = set()
        for package_ref in item.get("package_refs", []):
            for gradle_module_ref in item.get("gradle_module_refs", gradle_modules):
                source_sets, relative_paths = find_package_binding_locations(
                    source_project_path=source_project_path,
                    gradle_module_ref=gradle_module_ref,
                    package_ref=package_ref,
                )
                if not source_sets:
                    continue
                key = (package_ref, gradle_module_ref)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                bindings.append(
                    {
                        "package_ref": package_ref,
                        "gradle_module_ref": gradle_module_ref,
                        "source_sets": source_sets,
                        "relative_paths": relative_paths,
                    }
                )
        module_copy["package_bindings"] = bindings
        upgraded.append(module_copy)
    return upgraded


def find_package_binding_locations(
    source_project_path: str,
    gradle_module_ref: str,
    package_ref: str,
) -> Tuple[List[str], List[str]]:
    module_relpath = gradle_module_ref.lstrip(":").replace(":", os.sep)
    module_root = os.path.join(source_project_path, module_relpath)
    src_root = os.path.join(module_root, "src")
    if not os.path.isdir(src_root):
        return [], []

    if package_ref == "org.wikipedia.__root__":
        package_tail = os.path.join("org", "wikipedia")
    else:
        package_tail = os.path.join(*package_ref.split("."))

    source_sets: List[str] = []
    relative_paths: List[str] = []
    for source_set in sorted(os.listdir(src_root)):
        java_root = os.path.join(src_root, source_set, "java")
        candidate_dir = os.path.join(java_root, package_tail)
        if os.path.isdir(candidate_dir):
            source_sets.append(source_set)
            relative_paths.append(os.path.relpath(candidate_dir, source_project_path))
    return source_sets, relative_paths


def collect_ui_components(
    source_project_path: str,
    module_package_map: Dict[str, List[str]],
) -> Tuple[List[UIComponent], List[str]]:
    manifest_activities, _aliases = parse_manifest_entries(
        os.path.join(source_project_path, "app", "src", "main", "AndroidManifest.xml")
    )
    manifest_ref_set = {normalize_manifest_class_name(name) for name in manifest_activities}
    business_like_packages = {
        package_ref
        for package_ref, module_ids in module_package_map.items()
        if any(not module_id.startswith("mod_infrastructure") for module_id in module_ids)
    }

    components: Dict[str, UIComponent] = {}
    app_src_root = os.path.join(source_project_path, "app", "src")
    if os.path.isdir(app_src_root):
        for source_set in sorted(os.listdir(app_src_root)):
            if "test" in source_set.lower():
                continue
            java_root = os.path.join(app_src_root, source_set, "java")
            if not os.path.isdir(java_root):
                continue
            for dirpath, dirnames, filenames in os.walk(java_root):
                dirnames[:] = [name for name in dirnames if name not in {"build", ".git", "__pycache__"}]
                for filename in filenames:
                    if not filename.endswith((".kt", ".java")):
                        continue
                    full_path = os.path.join(dirpath, filename)
                    source_relpath = os.path.relpath(full_path, source_project_path)
                    package_ref = package_ref_from_source_path(source_relpath)
                    if not package_ref or package_ref not in business_like_packages:
                        continue
                    content = read_text(full_path)
                    for component_type, symbol_name in extract_ui_symbols(content):
                        fqcn = f"{package_ref}.{symbol_name}"
                        component_ref = f"{component_type}:{fqcn}"
                        components[component_ref] = UIComponent(
                            component_ref=component_ref,
                            component_type=component_type,
                            symbol_name=symbol_name,
                            fqcn=fqcn,
                            package_ref=package_ref,
                            source_path=full_path,
                            source_relpath=source_relpath,
                            source_set=source_set,
                            module_ids=resolve_module_ids_for_package(package_ref, module_package_map),
                            manifest_declared=fqcn in manifest_ref_set,
                        )

    manifest_activity_refs: List[str] = []
    for activity_name in manifest_ref_set:
        component_ref = f"activity:{activity_name}"
        manifest_activity_refs.append(component_ref)
        if component_ref not in components:
            package_ref = ".".join(activity_name.split(".")[:-1])
            components[component_ref] = UIComponent(
                component_ref=component_ref,
                component_type="activity",
                symbol_name=activity_name.split(".")[-1],
                fqcn=activity_name,
                package_ref=package_ref,
                source_path="",
                source_relpath="AndroidManifest.xml",
                source_set="main",
                module_ids=resolve_module_ids_for_package(package_ref, module_package_map),
                manifest_declared=True,
            )

    component_list = list(components.values())
    component_list.sort(key=lambda item: (item.component_type, item.fqcn))
    return component_list, sorted(manifest_activity_refs)


def parse_manifest_entries(manifest_path: str) -> Tuple[List[str], List[str]]:
    if not os.path.exists(manifest_path):
        return [], []
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    android_ns = "{http://schemas.android.com/apk/res/android}"
    activities: List[str] = []
    aliases: List[str] = []
    for elem in root.findall(".//activity"):
        name = elem.attrib.get(f"{android_ns}name")
        if name:
            activities.append(name)
    for elem in root.findall(".//activity-alias"):
        name = elem.attrib.get(f"{android_ns}name")
        if name:
            aliases.append(name)
    return activities, aliases


def normalize_manifest_class_name(name: str) -> str:
    if name.startswith("."):
        return f"org.wikipedia{name}"
    return name


def package_ref_from_source_path(source_relpath: str) -> Optional[str]:
    marker = f"java{os.sep}"
    if marker not in source_relpath:
        return None
    package_part = source_relpath.split(marker, 1)[1]
    segments = package_part.split(os.sep)
    if len(segments) < 2:
        return None
    return ".".join(segments[:-1])


def extract_ui_symbols(content: str) -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    class_pattern = re.compile(
        r"class\s+([A-Z][A-Za-z0-9_]*)"
        r"(?:\s*<[^>{}]*>)?"
        r"(?:\s*\([^)]*\))?"
        r"\s*(?::\s*([^\n{]*))?"
    )
    for match in class_pattern.finditer(content):
        symbol_name = match.group(1)
        remainder = match.group(2) or ""
        base_types = extract_declared_base_types(remainder)
        component_type: Optional[str] = None
        if symbol_name.endswith("Activity") or any(base.endswith("Activity") for base in base_types):
            component_type = "activity"
        elif (
            symbol_name.endswith("Dialog")
            or "BottomSheet" in symbol_name
            or any(
                base.endswith("DialogFragment")
                or base.endswith("BottomSheetDialogFragment")
                or base.endswith("Dialog")
                for base in base_types
            )
        ):
            component_type = "dialog"
        elif symbol_name.endswith("Fragment") or any(base.endswith("Fragment") for base in base_types):
            component_type = "fragment"
        if component_type:
            item = (component_type, symbol_name)
            if item not in seen:
                found.append(item)
                seen.add(item)

    function_pattern = re.compile(r"fun\s+([A-Z][A-Za-z0-9_]*Screen)\s*\(")
    for match in function_pattern.finditer(content):
        item = ("compose_screen", match.group(1))
        if item not in seen:
            found.append(item)
            seen.add(item)

    return found


def extract_declared_base_types(remainder: str) -> List[str]:
    if not remainder.strip():
        return []
    tokens = re.findall(r"([A-Za-z_][A-Za-z0-9_.]*)\s*(?:<[^>]*>)?\s*(?:\(|,|$)", remainder)
    normalized: List[str] = []
    for token in tokens:
        normalized.append(token.split(".")[-1])
    return normalized


def build_page_analysis_prompt(
    snapshot: PageAnalysisSnapshot,
    unknown_threshold: int,
    previous_response: Optional[Dict[str, Any]] = None,
    previous_issues: Optional[Sequence[str]] = None,
) -> str:
    module_lines = []
    for module in snapshot.module_index:
        module_lines.append(
            f"- {module['module_id']} | {module['name']} | type={module['type']} | "
            f"packages={','.join(module.get('package_refs', [])[:10])}"
        )

    component_lines = []
    for component in snapshot.components:
        component_lines.append(
            f"- {component.component_ref} | type={component.component_type} | "
            f"package={component.package_ref} | source_set={component.source_set} | "
            f"modules={','.join(component.module_ids) or '(none)'} | "
            f"manifest={component.manifest_declared} | path={component.source_relpath}"
        )

    previous_block = ""
    if previous_response is not None and previous_issues:
        previous_block = (
            "\n上一次输出未通过本地审阅。请只做纠错，不要减少覆盖范围。\n"
            + "上一次问题：\n- " + "\n- ".join(previous_issues) + "\n"
            + f"上一次输出：\n{json.dumps(previous_response, ensure_ascii=False, indent=2)}\n"
        )

    schema = {
        "analysis_summary": "string",
        "page_index": [
            {
                "page_id": "string",
                "name": "string",
                "page_kind": "activity|fragment_page|dialog|compose_screen|settings|onboarding|support",
                "module_ids": ["string"],
                "primary_component_refs": ["string"],
                "supporting_component_refs": ["string"],
                "entry_activity_refs": ["string"],
                "route_hint": "string",
                "user_visible": True,
                "summary": "string",
                "unknown_refs": ["string"],
            }
        ],
        "ignored_components": [
            {
                "component_ref": "string",
                "reason": "string",
            }
        ],
        "unknowns": [
            {
                "unknown_id": "string",
                "title": "string",
                "description": "string",
                "category": "page_mapping|entrypoint|feature_gating|navigation",
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
            "covered_component_refs": ["string"],
            "ignored_component_refs": ["string"],
            "missing_component_refs": ["string"],
            "notes": ["string"],
        },
    }

    return f"""请基于已有 module_index 和以下 UI 组件候选，输出页面层全量分析结果。

当前任务边界：
- 只做阶段 2：页面层分析
- 不做用户流程层
- 每个 manifest activity 必须落入 page_index
- 其他高信号 UI 组件必须进入 page_index 或 ignored_components

已知模块：
{chr(10).join(module_lines)}

manifest activity refs（必须全部被页面覆盖）：
{json.dumps(snapshot.manifest_activity_refs, ensure_ascii=False)}

UI component candidates：
{chr(10).join(component_lines)}
{previous_block}
输出约束：
1. 只输出一个 JSON 对象。
2. 所有 manifest activity refs 必须出现在某个 page.primary_component_refs 或 page.entry_activity_refs 中。
3. 所有 component candidates 都必须进入 page_index 或 ignored_components。
4. 不允许忽略 activity 组件，除非它是 icon alias；本次候选里已排除 alias。
5. ignored_components 必须给出具体理由，不能写泛泛的“非页面”。
6. 每个 page 至少绑定一个 module_id。
7. 当 max(uncertainty_score, severity_score) >= {unknown_threshold} 时，needs_user_confirmation 必须为 true。

输出 schema 示例：
{json.dumps(schema, ensure_ascii=False, indent=2)}
"""


def chunked(items: Sequence[str], size: int) -> List[List[str]]:
    return [list(items[idx: idx + size]) for idx in range(0, len(items), size)]


def build_activity_chunk_prompt(
    snapshot: PageAnalysisSnapshot,
    activity_refs: Sequence[str],
    unknown_threshold: int,
    previous_response: Optional[Dict[str, Any]] = None,
    previous_issues: Optional[Sequence[str]] = None,
) -> str:
    module_lines = []
    for module in snapshot.module_index:
        module_lines.append(
            f"- {module['module_id']} | {module['name']} | type={module['type']} | "
            f"packages={','.join(module.get('package_refs', [])[:8])}"
        )

    activity_lines = []
    for ref in activity_refs:
        component = snapshot.component_by_ref[ref]
        activity_lines.append(
            f"- {ref} | package={component.package_ref} | modules={','.join(component.module_ids)} | "
            f"manifest={component.manifest_declared}"
        )

    previous_block = ""
    if previous_response is not None and previous_issues:
        previous_block = (
            "\n上一次输出未通过本地审阅。请只做纠错，不要减少覆盖范围。\n"
            + "上一次问题：\n- " + "\n- ".join(previous_issues) + "\n"
            + f"上一次输出：\n{json.dumps(previous_response, ensure_ascii=False, indent=2)}\n"
        )

    schema = {
        "analysis_summary": "string",
        "page_index": [
            {
                "page_id": "string",
                "name": "string",
                "page_kind": "activity|settings|onboarding|support",
                "module_ids": ["string"],
                "primary_component_refs": ["activity:org.wikipedia.SomeActivity"],
                "supporting_component_refs": [],
                "entry_activity_refs": ["activity:org.wikipedia.SomeActivity"],
                "route_hint": "string",
                "user_visible": True,
                "summary": "string",
                "unknown_refs": ["string"],
            }
        ],
        "unknowns": [
            {
                "unknown_id": "string",
                "title": "string",
                "description": "string",
                "category": "page_mapping|entrypoint|feature_gating|navigation",
                "evidence_refs": ["string"],
                "candidate_options": ["string"],
                "recommended_option": "string",
                "uncertainty_score": 0,
                "severity_score": 0,
                "impact_scope": ["string"],
                "needs_user_confirmation": True,
            }
        ],
    }

    return f"""请基于 module_index 和以下 activity 组件，输出页面层的 activity page 清单。

当前任务边界：
- 只分析下面列出的 activity refs
- 每个 activity ref 必须映射成一个独立 page
- 这一步不要处理 fragment/dialog/compose screen
- 不允许忽略 activity

已知模块：
{chr(10).join(module_lines)}

activity refs:
{chr(10).join(activity_lines)}
{previous_block}
输出约束：
1. 只输出一个 JSON 对象。
2. page_index 中必须覆盖当前列表里的全部 activity refs。
3. 每个 page.primary_component_refs 必须且只能包含 1 个当前 chunk 的 activity_ref。
4. supporting_component_refs 此阶段保持空数组。
5. 当 max(uncertainty_score, severity_score) >= {unknown_threshold} 时，needs_user_confirmation 必须为 true。

输出 schema 示例：
{json.dumps(schema, ensure_ascii=False, indent=2)}
"""


def review_activity_chunk(
    data: Dict[str, Any],
    activity_refs: Sequence[str],
    known_module_ids: Sequence[str],
    unknown_threshold: int,
) -> PageReviewResult:
    issues: List[str] = []

    if not isinstance(data.get("analysis_summary"), str) or not data.get("analysis_summary", "").strip():
        issues.append("analysis_summary 缺失或为空")

    page_index = data.get("page_index")
    if not isinstance(page_index, list) or not page_index:
        issues.append("page_index 缺失或为空")
        return PageReviewResult(False, issues)

    unknowns = data.get("unknowns", [])
    if not isinstance(unknowns, list):
        issues.append("unknowns 必须是数组")
        unknowns = []

    known_unknown_ids: Set[str] = set()
    for item in unknowns:
        try:
            validate_unknown_item(item, None)
        except ProjectMemoryValidationError as e:
            issues.append(f"unknown 非法: {e}")
            continue
        known_unknown_ids.add(item["unknown_id"])
        decision_score = max(item["uncertainty_score"], item["severity_score"])
        if decision_score >= unknown_threshold and not item["needs_user_confirmation"]:
            issues.append(f"unknown {item['unknown_id']} 超过阈值但未标记 needs_user_confirmation")

    covered_activity_refs: Set[str] = set()
    page_ids: Set[str] = set()
    for item in page_index:
        if not isinstance(item, dict):
            issues.append("page_index 中每项必须是对象")
            continue
        page_id = item.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            issues.append("page.page_id 缺失")
            continue
        if page_id in page_ids:
            issues.append(f"page_id 重复: {page_id}")
        page_ids.add(page_id)

        module_ids = item.get("module_ids")
        if not isinstance(module_ids, list) or not module_ids:
            issues.append(f"{page_id} 缺少 module_ids")
        else:
            for module_id in module_ids:
                if module_id not in known_module_ids:
                    issues.append(f"{page_id} 包含未知 module_id: {module_id}")

        primary_refs = item.get("primary_component_refs", [])
        if not isinstance(primary_refs, list) or not primary_refs:
            issues.append(f"{page_id}.primary_component_refs 缺失或为空")
            continue
        if len(primary_refs) != 1:
            issues.append(f"{page_id}.primary_component_refs 在 activity chunk 阶段必须只包含 1 个 activity_ref")
        for ref in primary_refs:
            if ref not in activity_refs:
                issues.append(f"{page_id} 包含非本 chunk 的 activity_ref: {ref}")
            covered_activity_refs.add(ref)

        supporting_refs = item.get("supporting_component_refs", [])
        if supporting_refs not in ([], None):
            issues.append(f"{page_id}.supporting_component_refs 在 activity chunk 阶段必须为空")

        unknown_refs = item.get("unknown_refs", [])
        if not isinstance(unknown_refs, list):
            issues.append(f"{page_id}.unknown_refs 必须是数组")
            continue
        for unknown_ref in unknown_refs:
            if unknown_ref not in known_unknown_ids:
                issues.append(f"{page_id} 引用了未知 unknown_id: {unknown_ref}")

    missing = sorted(set(activity_refs) - covered_activity_refs)
    if missing:
        issues.append(f"activity refs 未被页面覆盖: {missing}")
    if len(page_index) != len(activity_refs):
        issues.append("activity chunk 页面数与 activity refs 数量不一致")

    return PageReviewResult(accepted=not issues, issues=issues)


def normalize_activity_chunk_response(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_page_analysis(
        {
            "analysis_summary": data.get("analysis_summary", ""),
            "page_index": data.get("page_index", []),
            "ignored_components": [],
            "unknowns": data.get("unknowns", []),
            "coverage": {},
        }
    )
    for item in normalized["page_index"]:
        item["supporting_component_refs"] = []
    return normalized


def augment_page_analysis_with_support_components(
    snapshot: PageAnalysisSnapshot,
    normalized: Dict[str, Any],
    unknown_threshold: int,
) -> Dict[str, Any]:
    page_index = [dict(item) for item in normalized.get("page_index", [])]
    unknowns = list(normalized.get("unknowns", []))
    ignored_components = list(normalized.get("ignored_components", []))

    covered_component_refs: Set[str] = set()
    for page in page_index:
        for field_name in ("primary_component_refs", "supporting_component_refs", "entry_activity_refs"):
            covered_component_refs.update(page.get(field_name, []))

    package_page_map: Dict[str, List[Dict[str, Any]]] = {}
    for page in page_index:
        primary_activity_refs = [
            ref for ref in page.get("primary_component_refs", [])
            if snapshot.component_by_ref.get(ref) and snapshot.component_by_ref[ref].component_type == "activity"
        ]
        for ref in primary_activity_refs:
            package_ref = snapshot.component_by_ref[ref].package_ref
            package_page_map.setdefault(package_ref, []).append(page)

    for component in snapshot.components:
        if component.component_ref in covered_component_refs:
            continue

        candidate_pages = package_page_map.get(component.package_ref, [])
        if not candidate_pages:
            candidate_pages = find_prefix_matched_pages(component.package_ref, package_page_map)

        if len(candidate_pages) == 1 and component.component_type != "activity":
            page = candidate_pages[0]
            page.setdefault("supporting_component_refs", [])
            if component.component_ref not in page["supporting_component_refs"]:
                page["supporting_component_refs"].append(component.component_ref)
                covered_component_refs.add(component.component_ref)
            continue

        if component.component_type != "activity" and len(candidate_pages) > 1:
            chosen_page = sorted(candidate_pages, key=lambda item: item["page_id"])[0]
            chosen_page.setdefault("supporting_component_refs", [])
            if component.component_ref not in chosen_page["supporting_component_refs"]:
                chosen_page["supporting_component_refs"].append(component.component_ref)
                covered_component_refs.add(component.component_ref)
            unknown_id = f"unk_page_attach_{_slugify(component.symbol_name)}"
            unknowns.append(
                build_component_attachment_unknown(
                    component=component,
                    candidate_pages=candidate_pages,
                    unknown_id=unknown_id,
                    unknown_threshold=unknown_threshold,
                )
            )
            chosen_page.setdefault("unknown_refs", [])
            chosen_page["unknown_refs"] = sorted(dict.fromkeys(chosen_page["unknown_refs"] + [unknown_id]))
            continue

        support_page = build_support_page(component)
        page_index.append(support_page)
        covered_component_refs.update(support_page["primary_component_refs"])
        covered_component_refs.update(support_page["entry_activity_refs"])
        package_page_map.setdefault(component.package_ref, []).append(support_page)

    normalized["page_index"] = normalize_page_analysis(
        {
            "analysis_summary": normalized.get("analysis_summary", ""),
            "page_index": page_index,
            "ignored_components": ignored_components,
            "unknowns": unknowns,
            "coverage": {},
        }
    )["page_index"]
    normalized["unknowns"] = normalize_page_analysis(
        {
            "analysis_summary": "",
            "page_index": [],
            "ignored_components": [],
            "unknowns": merge_unknowns([], unknowns),
            "coverage": {},
        }
    )["unknowns"]
    normalized["ignored_components"] = ignored_components
    normalized["coverage"] = {
        "covered_component_refs": sorted({ref for page in normalized["page_index"] for key in ("primary_component_refs", "supporting_component_refs", "entry_activity_refs") for ref in page.get(key, [])}),
        "ignored_component_refs": [item.get("component_ref") for item in ignored_components],
        "missing_component_refs": sorted(snapshot.component_ref_set - {ref for page in normalized["page_index"] for key in ("primary_component_refs", "supporting_component_refs", "entry_activity_refs") for ref in page.get(key, [])}),
        "notes": ["supporting_component_refs 中的非 activity 组件由 orchestrator 根据 package 归属自动补齐"],
    }
    return normalized


def find_prefix_matched_pages(package_ref: str, package_page_map: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    best_prefix_len = -1
    matched_pages: List[Dict[str, Any]] = []
    for known_package_ref, pages in package_page_map.items():
        if package_ref.startswith(f"{known_package_ref}."):
            prefix_len = len(known_package_ref)
            if prefix_len > best_prefix_len:
                best_prefix_len = prefix_len
                matched_pages = list(pages)
            elif prefix_len == best_prefix_len:
                matched_pages.extend(pages)
    dedup: Dict[str, Dict[str, Any]] = {}
    for item in matched_pages:
        dedup[item["page_id"]] = item
    return list(dedup.values())


def build_component_attachment_unknown(
    component: UIComponent,
    candidate_pages: Sequence[Dict[str, Any]],
    unknown_id: str,
    unknown_threshold: int,
) -> Dict[str, Any]:
    score = max(unknown_threshold + 5, 65)
    return {
        "unknown_id": unknown_id,
        "title": f"{component.symbol_name} 页面归属待确认",
        "description": f"{component.component_ref} 可归属多个页面，当前按 package 规则临时挂载，需人工复核。",
        "category": "page_mapping",
        "evidence_refs": [component.source_relpath],
        "candidate_options": [page["page_id"] for page in candidate_pages],
        "recommended_option": candidate_pages[0]["page_id"],
        "uncertainty_score": score,
        "severity_score": 45,
        "impact_scope": [component.component_ref],
        "needs_user_confirmation": True,
        "status": "open",
        "recheck_count": 0,
    }


def build_support_page(component: UIComponent) -> Dict[str, Any]:
    page_kind_map = {
        "activity": "activity",
        "fragment": "fragment_page",
        "dialog": "dialog",
        "compose_screen": "compose_screen",
    }
    return {
        "page_id": f"page_auto_{_slugify(component.symbol_name)}",
        "name": component.symbol_name,
        "page_kind": page_kind_map.get(component.component_type, "support"),
        "module_ids": component.module_ids,
        "primary_component_refs": [component.component_ref],
        "supporting_component_refs": [],
        "entry_activity_refs": [component.component_ref] if component.component_type == "activity" and component.manifest_declared else [],
        "route_hint": _slugify(component.symbol_name),
        "user_visible": component.component_type in {"activity", "fragment", "dialog", "compose_screen"},
        "summary": "Auto-generated support page pending later refinement.",
        "unknown_refs": [],
    }


def review_page_analysis(data: Dict[str, Any], snapshot: PageAnalysisSnapshot, unknown_threshold: int) -> PageReviewResult:
    issues: List[str] = []

    if not isinstance(data.get("analysis_summary"), str) or not data.get("analysis_summary", "").strip():
        issues.append("analysis_summary 缺失或为空")

    page_index = data.get("page_index")
    if not isinstance(page_index, list) or not page_index:
        issues.append("page_index 缺失或为空")
        return PageReviewResult(False, issues)

    ignored_components = data.get("ignored_components", [])
    if not isinstance(ignored_components, list):
        issues.append("ignored_components 必须是数组")
        ignored_components = []

    unknowns = data.get("unknowns", [])
    if not isinstance(unknowns, list):
        issues.append("unknowns 必须是数组")
        unknowns = []

    known_unknown_ids: Set[str] = set()
    for item in unknowns:
        try:
            validate_unknown_item(item, None)
        except ProjectMemoryValidationError as e:
            issues.append(f"unknown 非法: {e}")
            continue
        unknown_id = item["unknown_id"]
        if unknown_id in known_unknown_ids:
            issues.append(f"unknown_id 重复: {unknown_id}")
        known_unknown_ids.add(unknown_id)
        decision_score = max(item["uncertainty_score"], item["severity_score"])
        if decision_score >= unknown_threshold and not item["needs_user_confirmation"]:
            issues.append(f"unknown {unknown_id} 超过阈值但未标记 needs_user_confirmation")

    covered_component_refs: Set[str] = set()
    activity_covered: Set[str] = set()
    page_ids: Set[str] = set()
    for item in page_index:
        if not isinstance(item, dict):
            issues.append("page_index 中每项必须是对象")
            continue
        page_id = item.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            issues.append("page.page_id 缺失")
            continue
        if page_id in page_ids:
            issues.append(f"page_id 重复: {page_id}")
        page_ids.add(page_id)

        module_ids = item.get("module_ids")
        if not isinstance(module_ids, list) or not module_ids:
            issues.append(f"{page_id} 缺少 module_ids")
        else:
            for module_id in module_ids:
                if module_id not in snapshot.module_ids:
                    issues.append(f"{page_id} 包含未知 module_id: {module_id}")

        unknown_refs = item.get("unknown_refs", [])
        if not isinstance(unknown_refs, list):
            issues.append(f"{page_id}.unknown_refs 必须是数组")
            unknown_refs = []
        for unknown_ref in unknown_refs:
            if unknown_ref not in known_unknown_ids:
                issues.append(f"{page_id} 引用了未知 unknown_id: {unknown_ref}")

        for field_name in ("primary_component_refs", "supporting_component_refs", "entry_activity_refs"):
            refs = item.get(field_name, [])
            if not isinstance(refs, list):
                issues.append(f"{page_id}.{field_name} 必须是数组")
                continue
            for ref in refs:
                if ref not in snapshot.component_ref_set:
                    issues.append(f"{page_id} 引用了未知 component_ref: {ref}")
                    continue
                covered_component_refs.add(ref)
                component = snapshot.component_by_ref[ref]
                if component.component_type == "activity":
                    activity_covered.add(ref)

    ignored_refs: Set[str] = set()
    for item in ignored_components:
        if not isinstance(item, dict):
            issues.append("ignored_components 中每项必须是对象")
            continue
        ref = item.get("component_ref")
        reason = item.get("reason")
        if not isinstance(ref, str) or ref not in snapshot.component_ref_set:
            issues.append(f"ignored_components 包含未知 component_ref: {ref}")
            continue
        if not isinstance(reason, str) or not reason.strip():
            issues.append(f"ignored_components 缺少 reason: {ref}")
        ignored_refs.add(ref)
        if snapshot.component_by_ref[ref].component_type == "activity":
            issues.append(f"不允许忽略 activity 组件: {ref}")

    minimum_page_count = max(
        len(snapshot.manifest_activity_refs),
        min(20, max(4, math.ceil(len(snapshot.components) * 0.45))),
    )
    if len(page_index) < minimum_page_count:
        issues.append("page_index 过少，页面层拆分过粗")

    missing_manifest = sorted(set(snapshot.manifest_activity_refs) - activity_covered)
    if missing_manifest:
        issues.append(f"manifest activities 未被页面覆盖: {missing_manifest}")

    candidate_refs = snapshot.component_ref_set
    uncovered_components = sorted(candidate_refs - covered_component_refs - ignored_refs)
    if uncovered_components:
        issues.append(f"高信号 UI 组件未被页面或 ignored_components 覆盖: {uncovered_components[:40]}")

    non_activity_candidates = [ref for ref in candidate_refs if snapshot.component_by_ref[ref].component_type != "activity"]
    if non_activity_candidates and len(ignored_refs) > int(len(non_activity_candidates) * 0.45):
        issues.append("ignored_components 过多，疑似页面覆盖不足")

    return PageReviewResult(accepted=not issues, issues=issues)


def normalize_page_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    page_index: List[Dict[str, Any]] = []
    unknowns: List[Dict[str, Any]] = []
    for page in data.get("page_index", []):
        item = dict(page)
        for key in ("module_ids", "primary_component_refs", "supporting_component_refs", "entry_activity_refs", "unknown_refs"):
            item[key] = sorted(dict.fromkeys(item.get(key, [])))
        page_index.append(item)
    for unknown in data.get("unknowns", []):
        item = dict(unknown)
        item.setdefault("status", "open")
        item.setdefault("recheck_count", 0)
        item["decision_score"] = max(item["uncertainty_score"], item["severity_score"])
        unknowns.append(item)
    return {
        "analysis_summary": data.get("analysis_summary", ""),
        "page_index": page_index,
        "ignored_components": data.get("ignored_components", []),
        "unknowns": unknowns,
        "coverage": data.get("coverage", {}),
    }


def merge_unknowns(existing: List[Dict[str, Any]], new_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for item in existing + new_items:
        merged[item["unknown_id"]] = item
    return list(merged.values())


def render_pages_markdown(snapshot: PageAnalysisSnapshot, normalized: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# 页面层分析")
    lines.append("")
    lines.append(f"- Source project: `{snapshot.source_project_path}`")
    lines.append(f"- Project memory: `{snapshot.project_memory_path}`")
    lines.append(f"- Manifest activities: {len(snapshot.manifest_activity_refs)}")
    lines.append(f"- UI components: {len(snapshot.components)}")
    lines.append("")
    lines.append("## 总结")
    lines.append("")
    lines.append(normalized.get("analysis_summary", ""))
    lines.append("")
    lines.append("## 页面")
    lines.append("")
    for page in normalized["page_index"]:
        lines.append(f"### {page['name']}")
        lines.append("")
        lines.append(f"- id: `{page['page_id']}`")
        lines.append(f"- kind: `{page['page_kind']}`")
        lines.append(f"- modules: {', '.join(page['module_ids'])}")
        lines.append(f"- primary: {', '.join(page['primary_component_refs'])}")
        lines.append(f"- supporting: {', '.join(page['supporting_component_refs']) or '(none)'}")
        lines.append(f"- entry activities: {', '.join(page['entry_activity_refs']) or '(none)'}")
        lines.append(f"- user visible: `{page['user_visible']}`")
        lines.append(f"- route hint: {page['route_hint'] or '(none)'}")
        lines.append(f"- summary: {page['summary']}")
        lines.append("")
    lines.append("## Unknowns")
    lines.append("")
    if not normalized["unknowns"]:
        lines.append("- none")
    else:
        for item in normalized["unknowns"]:
            lines.append(
                f"- `{item['unknown_id']}`: {item['title']} "
                f"(decision_score={item['decision_score']}, needs_user_confirmation={item['needs_user_confirmation']})"
            )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()
