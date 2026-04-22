# hm_agent

`hm_agent` 的最终产品形态是：

一个面向移动端源码工程的 `source app -> HarmonyOS` 迁移 agent。用户可以替换源项目为 Android、iOS、Flutter 或其它移动端工程，并向 agent 下达一次迁移指令；agent 负责识别项目结构、分析业务覆盖、规划目标鸿蒙工程、迁移大部分代码、持续修复构建与测试问题，并把未能自动闭环的部分沉淀为可追踪 gap。

当前 MVP-1 的产品目标已经收敛为：

一个面向单一真实项目的 `Android -> HarmonyOS` 迁移分析 orchestrator。

它不是直接把整个迁移一次性做完，也不是先抽象成通用 builder 再找场景验证。当前阶段更务实的目标是：

- 围绕固定 Android 源工程做全量、分层分析
- 驱动 `qwen` 输出可持续修正的结构化 `project memory`
- 在关键不确定项处暂停，并通过待确认项清单与用户协作
- 为后续多会话、TDD 驱动的迁移实现和多源工程泛化提供唯一 roadmap

## 当前 MVP-1 目标

当前 MVP 不是“生成完整迁移 agent 工程”，而是“把迁移分析闭环跑通”。

MVP-1 的交付物是：

- 落在目标鸿蒙工程内的结构化 `project_memory/`
- 分层分析产物
- unknown / gap 持续跟踪与复查机制
- 待确认项清单与恢复继续能力
- 高可读 Markdown 导出文档

当前固定目标项目：

- Android 源工程：
  `/Users/weibaoping/Android/opensource/wikipedia-android/apps-android-wikipedia/`
- HarmonyOS template 工程：
  `/Users/weibaoping/ohos/migrate/wiki/`

最终形态仍然是对可替换源项目迁移出可编译、可运行、主要功能页面可达的 HarmonyOS 工程；但跨 Android / iOS / Flutter 泛化、完整实现闭环和回归测试闭环属于后续阶段，不是当前 MVP-1 的范围。

## 产品原则

- 先服务一个固定项目，再考虑抽象通用性
- 固定 Wikipedia Android 项目是第一块验证样板，不是最终产品边界
- 每一层分析都要求当前层全量覆盖，不做“最小实现”
- 以 `模块 + 页面/流程 + 功能点` 三视角交叉防漏
- `project memory` 是事实源，Markdown 只是导出视图
- 具体迁移项目产物必须落在目标鸿蒙工程内，而不是当前 agent 仓库内
- 不确定项必须持续携带、反查、消解，不能伪确定
- 高风险 unknown 才暂停并请求人工确认
- 低风险 unknown 可由 agent 按规则自治，但必须记录依据

## 当前仓库状态

当前项目已完成里程碑 1，并已进入 MVP-1 的迁移分析闭环，现状更准确地说是：

- 已有统一执行主干
- 已有统一事件协议、停止原因与 trace 输出
- 已有 chat / session 记忆
- 已有最小权限阻断
- 已有基线测试
- 已有 `project_memory` 存储层、模块层和页面层分析
- 已有 unknown 队列筛选、聚合、确认、延后和阈值调整 CLI
- 已有 CLI 与 OpenAI 风格 Web 入口

当前仍缺少：

- 流程层、功能点层、实现骨架层、测试骨架层
- 多轮 unknown 收敛、复查与最终 gap 闭环
- 基于 `project_memory` 的 HarmonyOS 代码迁移实现闭环
- 多源工程适配层：Android 以外的 iOS、Flutter 等源项目识别与分析

## 当前正式入口

- `scripts/chat_agent.py`
- `scripts/openai_adapter.py`
- `scripts/run_phase1_module_analysis.py`
- `scripts/run_stage2_page_analysis.py`
- `scripts/review_unknown_queue.py`

## 当前支持能力

- 交互式 CLI 调试
- OpenAI 风格 Web 适配层
- 工具调用与事件追踪
- chat / session 持久化
- 以当前代码库为对象的增量演进
- 分类停止原因：
  - `final`
  - `max_steps`
  - `permission_blocked`
  - `tool_error`
  - `llm_error`
  - `invalid_model_output`

## 当前限制

- 还没有流程层、功能点层、实现层、测试层的正式编排
- 权限策略目前仍是最小可控版本：
  - 只读命令默认允许
  - `run_command` 的工作区外路径修改会先申请授权
  - CLI 中用户同意后会永久写入授权配置
  - Web 中可通过 `/approve <path>` 做永久授权

## 快速开始

### 1. 查看当前 LLM

```bash
python3 scripts/llm_provider.py which
```

### 2. 如有需要，切换当前 LLM

```bash
python3 scripts/llm_provider.py ls
python3 scripts/llm_provider.py checkout qwen
```

LLM 的 `model`、`api_key`、`base_url` 都统一写在 [config.json](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/config.json)。

### 3. 启动交互式 CLI

```bash
python3 scripts/chat_agent.py --root .
```

启动后可直接输入类似任务：

```text
请围绕 wikipedia Android 工程输出模块层全量分析，并把 unknown 项按阈值筛出待确认项清单
```

阶段分析产物默认会写到目标鸿蒙工程下的 `.migration/project_memory/`，不会再写到当前 agent 仓库根目录。

### 4.1 查看待人工确认项批次

```bash
python3 scripts/review_unknown_queue.py list \
  --target-template-project-path /Users/weibaoping/ohos/migrate/wiki/
```

### 4.2 按推荐项确认一批问题

```bash
python3 scripts/review_unknown_queue.py decide \
  --target-template-project-path /Users/weibaoping/ohos/migrate/wiki/ \
  --item-id cluster_5e612d14493b \
  --choice recommended \
  --rationale "搜索页相关组件先统一归属到主搜索页"
```

### 4.3 延后某批问题

```bash
python3 scripts/review_unknown_queue.py defer \
  --target-template-project-path /Users/weibaoping/ohos/migrate/wiki/ \
  --item-id unk_flavor_feature_gating \
  --rationale "等功能点层分析后再确认"
```

### 4.4 调整人工确认阈值

```bash
python3 scripts/review_unknown_queue.py set-threshold \
  --target-template-project-path /Users/weibaoping/ohos/migrate/wiki/ \
  --value 70
```

权限相关命令：

```bash
/permissions
/approve /path/to/allow
```

### 5. 启动 Web 适配层

```bash
python3 scripts/openai_adapter.py
```

如果 Web 请求被权限阻塞，可发送：

```text
/approve /path/to/allow
```

## 文档

- MVP 目标：[docs/MVP_minimum.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/MVP_minimum.md)
- 开发路线图：[docs/development_roadmap.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/development_roadmap.md)
- `project_memory` schema：[docs/project_memory_schema.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/project_memory_schema.md)
- 阶段机与 unknown 机制：[docs/analysis_orchestration.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/analysis_orchestration.md)
- 运行与配置：[docs/runtime_config.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/runtime_config.md)
- 基线测试：[docs/testing_baseline.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/testing_baseline.md)
- 记忆模块说明：[docs/memory_module.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/memory_module.md)

## 基线测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

当前基线测试不依赖真实 API key。

## 下一步

下一阶段重点是补齐里程碑 2 的后半段，并为里程碑 3 做准备：

- 推进流程层、功能点层、实现骨架层和测试骨架层
- 把 page analysis 后的 `project_overview`、coverage 与导出 manifest 保持同步
- 继续收敛 unknown 队列，形成人工确认、自治决策、复查和 final gap 闭环
- 基于稳定 `project_memory` 生成 HarmonyOS 实现任务与可执行迁移计划
