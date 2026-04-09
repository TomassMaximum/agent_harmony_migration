# `project_memory` Schema 与目录结构

## 目标

`project_memory/` 是 MVP-1 的核心产物目录。

它默认不应生成在当前 agent 工程仓库内，而应生成在目标鸿蒙工程根目录下：

```text
<target-harmony-project>/.migration/project_memory/
```

它的职责不是保存对话，而是保存迁移分析事实、状态和后续实现 roadmap。后续多会话实现必须以这里的内容为唯一事实源。

## 设计原则

- 结构化优先，Markdown 次之
- 所有核心对象都可增量更新
- 所有不确定项都可追踪状态
- 所有覆盖判断都能追溯证据
- 所有骨架结果都能映射到目标文件和测试入口

## 目录结构

建议最小目录如下：

```text
<target-harmony-project>/
  .migration/
    project_memory/
      builder_job.json
      project_overview.json
      coverage_status.json
      export_manifest.json
      indexes/
        module_index.json
        page_index.json
        flow_index.json
        feature_index.json
        file_index.json
        evidence_index.json
      unknowns/
        queue.json
        decisions.json
        final_gaps.json
      skeletons/
        implementation_index.json
        test_index.json
      exports/
        summary.md
        modules.md
        pages.md
        flows.md
        features.md
        unknowns.md
        skeletons.md
```

也就是说，当前 agent 仓库只保存 orchestrator 代码与通用文档，不保存某个具体迁移项目的产物目录；`project_memory/` 的内部结构则以上面的子目录为准。

## 顶层文件

### 1. `builder_job.json`

定义当前分析任务合同。

建议字段：

```json
{
  "job_id": "",
  "version": 1,
  "status": "draft | active | paused_for_confirmation | completed | blocked",
  "problem_type": "android_to_harmony_migration",
  "goal": "",
  "source_project_path": "",
  "target_template_project_path": "",
  "output_project_memory_path": "<target-harmony-project>/.migration/project_memory",
  "llm_execution_profile": {
    "primary_model": "qwen",
    "review_model": "same_orchestrator"
  },
  "confirmation_policy": {
    "unknown_score_threshold": 60,
    "max_items_per_batch": 10
  },
  "acceptance_criteria": [],
  "created_at": "",
  "updated_at": ""
}
```

### 2. `project_overview.json`

保存项目全局视图。

建议字段：

```json
{
  "project_name": "wikipedia-android",
  "analysis_scope": "single_project_mvp",
  "source_project_path": "",
  "target_template_project_path": "",
  "high_level_goal": "",
  "current_stage": "",
  "coverage_summary": {
    "modules_total": 0,
    "pages_total": 0,
    "flows_total": 0,
    "features_total": 0
  },
  "major_risks": [],
  "major_unknowns": [],
  "updated_at": ""
}
```

### 3. `coverage_status.json`

记录每一层的完成度和防漏校验结果。

建议字段：

```json
{
  "module_analysis": "not_started | in_progress | completed",
  "page_analysis": "not_started | in_progress | completed",
  "flow_analysis": "not_started | in_progress | completed",
  "feature_analysis": "not_started | in_progress | completed",
  "implementation_skeleton": "not_started | in_progress | completed",
  "test_skeleton": "not_started | in_progress | completed",
  "cross_checks": {
    "module_to_page": "pass | fail | partial",
    "page_to_flow": "pass | fail | partial",
    "flow_to_feature": "pass | fail | partial",
    "feature_to_file": "pass | fail | partial"
  },
  "updated_at": ""
}
```

### 4. `export_manifest.json`

记录导出文档与结构化对象之间的映射。

建议字段：

```json
{
  "exports": [
    {
      "name": "summary",
      "path": "exports/summary.md",
      "source_refs": [
        "project_overview.json",
        "coverage_status.json"
      ]
    }
  ],
  "updated_at": ""
}
```

## 索引目录

### 1. `indexes/module_index.json`

以模块为主索引。

每项至少包含：

- `module_id`
- `name`
- `description`
- `evidence_refs`
- `pages`
- `flows`
- `features`
- `unknown_refs`
- `status`

### 2. `indexes/page_index.json`

以页面为主索引。

每项至少包含：

- `page_id`
- `name`
- `route_or_entry`
- `source_refs`
- `module_refs`
- `flow_refs`
- `feature_refs`
- `target_harmony_mapping`
- `unknown_refs`

### 3. `indexes/flow_index.json`

以用户流程为主索引。

每项至少包含：

- `flow_id`
- `name`
- `trigger`
- `page_sequence`
- `feature_refs`
- `dependency_refs`
- `unknown_refs`

### 4. `indexes/feature_index.json`

以功能点为主索引，用于最终防漏。

每项至少包含：

- `feature_id`
- `name`
- `description`
- `source_evidence_refs`
- `module_refs`
- `page_refs`
- `flow_refs`
- `file_refs`
- `coverage_status`

### 5. `indexes/file_index.json`

以目标实现文件为主索引。

每项至少包含：

- `file_id`
- `path`
- `responsibility`
- `module_refs`
- `page_refs`
- `feature_refs`
- `behavior_contract_refs`
- `test_entry_refs`

### 6. `indexes/evidence_index.json`

证据索引，用来追溯所有分析结论来源。

每项至少包含：

- `evidence_id`
- `source_type`
- `source_path`
- `locator`
- `summary`
- `confidence`

## unknown 目录

### 1. `unknowns/queue.json`

保存所有活跃 unknown。

每项至少包含：

- `unknown_id`
- `title`
- `description`
- `category`
- `evidence_refs`
- `candidate_options`
- `recommended_option`
- `uncertainty_score`
- `severity_score`
- `impact_scope`
- `status`
- `needs_user_confirmation`
- `recheck_count`

### 2. `unknowns/decisions.json`

保存用户确认和 agent 自主决策记录。

每项至少包含：

- `decision_id`
- `unknown_id`
- `decision_type`
- `chosen_option`
- `decision_source`
- `rationale`
- `recorded_at`

### 3. `unknowns/final_gaps.json`

只保存完成全项目分析并复查后仍无法确认的问题。

每项至少包含：

- `gap_id`
- `derived_from_unknown_id`
- `description`
- `impact`
- `attempted_rechecks`
- `suggested_next_step`

## skeleton 目录

### 1. `skeletons/implementation_index.json`

记录实现骨架。

每项至少包含：

- `skeleton_id`
- `target_file_path`
- `kind`
- `module_refs`
- `page_refs`
- `feature_refs`
- `class_name`
- `method_signatures`
- `behavior_contracts`
- `mockable_dependencies`

### 2. `skeletons/test_index.json`

记录测试骨架。

每项至少包含：

- `test_skeleton_id`
- `target_test_file_path`
- `covers_file_refs`
- `covers_feature_refs`
- `test_cases`
- `required_mocks`

## 必须统一的通用字段

所有主要对象建议带上以下通用字段：

- `id`
- `version`
- `status`
- `created_at`
- `updated_at`
- `source_refs`
- `notes`

## 关键关系约束

### 1. 防漏约束

- 每个 `feature` 至少映射到一个 `module` 或 `page`
- 每个 `page` 至少归属一个 `flow`
- 每个关键 `feature` 最终应映射到一个 `file` 或明确 gap

### 2. 追溯约束

- 每个关键结论都应有 `evidence_refs`
- 每个 unknown 都应指向影响范围
- 每个 skeleton 都应能回溯到功能点

### 3. 续跑约束

- 新会话应优先读取 `project_memory/`
- 不能依赖读取全部历史 chat 才能继续

## 当前落地优先级

建议实现顺序：

1. `builder_job.json`
2. `project_overview.json`
3. `coverage_status.json`
4. `module/page/flow/feature/evidence` 五类索引
5. `unknowns/queue.json` 与 `decisions.json`
6. `implementation_index.json` 与 `test_index.json`
7. `export_manifest.json`
