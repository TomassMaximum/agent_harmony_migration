# 开发路线图

## 当前判断

当前仓库已经完成里程碑 1：运行底座收口，并已进入里程碑 2：迁移分析闭环。

已具备：

- `AgentLoop`
- 工具注册与 trace
- chat / session 记忆
- 最小权限机制
- CLI / Web 入口
- 基线测试
- `project_memory/` 存储层和目录结构
- 模块层分析与 Markdown 导出
- 页面层分析与 Markdown 导出
- unknown 队列筛选、聚合、确认、延后和阈值调整 CLI

目标鸿蒙工程内已经存在 `.migration/project_memory/` 产物。当前分析已完成模块层和页面层，尚未完成流程层、功能点层、实现骨架层、测试骨架层以及最终 gap 收敛。

长期产品方向是从当前 `Android -> HarmonyOS` 样板演进为 `source app -> HarmonyOS` 迁移 agent，后续支持替换源项目为 Android、iOS、Flutter 等移动端工程，并尽可能自动完成到鸿蒙工程的迁移实现。

## 路线原则

- 先把一个真实项目跑通，再抽象通用能力
- 固定 Wikipedia Android 项目是验证样板，不是最终产品边界
- 先把结构化 memory 和阶段机做硬，再谈自动实现
- 覆盖完整性优先于代码生成速度
- unknown 管理优先于“表面完整”

## 里程碑拆分

### Milestone 1：运行底座收口

目标：

- 统一 loop、tool、trace、memory、permission、CLI、Web

状态：

- 已完成

### Milestone 2：迁移分析闭环

目标：

- 引入 `project_memory/`
- 固化 `builder_job` 和索引 schema
- 落地阶段机
- 落地 unknown 跟踪、复查、待确认项清单
- 产出 Markdown 导出文档

状态：

- 部分完成
- 已落地 `project_memory` 基础结构、模块层分析、页面层分析、模块/页面 Markdown 导出和 unknown review CLI
- 未完成流程层、功能点层、实现骨架层、测试骨架层、unknown 复查和 final gap 闭环

### Milestone 3：实现骨架落地

目标：

- 基于 `project_memory` 生成 HarmonyOS 实现骨架
- 明确文件、类、方法、行为契约和测试入口
- 保持多会话续跑的一致事实源

### Milestone 4：迁移实现推进

目标：

- 按 memory roadmap 分会话推进 TDD 实现
- 在允许 mock 的条件下先打通主流程
- 缩小 gap 并提高页面可达率

### Milestone 5：最终交付闭环

目标：

- 可编译
- 可运行
- 主要功能页面可达
- gap 和验收文档完整

### Milestone 6：多源工程适配

目标：

- 抽象源工程适配层，不再把输入固定为 Wikipedia Android
- 支持 Android、iOS、Flutter 等源项目的结构识别、页面/流程抽取、资源与依赖建模
- 将不同源技术栈归一到统一 `project_memory` 中间事实模型

### Milestone 7：一条指令驱动的大部分自动迁移

目标：

- 用户提供源项目和目标鸿蒙工程后，agent 自动完成分析、规划、代码迁移、构建修复、测试推进和 gap 收敛
- 对无法自动迁移的功能给出证据、影响范围、建议方案和人工处理入口
- 让不同源项目复用同一套阶段机、memory、unknown 和实现闭环

## 当前应做的事情

### 1. 完成里程碑 2 后半段

必须继续落地：

- 流程层分析与 `flow_index.json`
- 功能点层分析与 `feature_index.json`
- 实现骨架与测试骨架
- unknown 复查、自治决策和 final gap
- `project_overview`、coverage、export manifest 的跨阶段同步

### 2. 开始实现骨架闭环

需要把 `project_memory` 从“分析事实源”推进为“实现任务源”：

- 基于模块、页面、流程、功能点生成目标文件清单
- 明确类、方法、行为契约、mock 决策和测试入口
- 为后续 HarmonyOS 代码生成和 TDD 实现提供稳定输入

### 3. 维护当前文档与实际产物一致

当前文档必须持续反映已落地能力，避免把已实现的 `project_memory`、页面层分析、unknown review CLI 写成规划中能力。

## 近期开发顺序

建议顺序如下：

1. 同步文档与当前工程状态
2. 修正 page analysis 后 `project_overview` 未更新页面统计的问题
3. 消解或延后当前 unknown review batch
4. 实现流程层分析
5. 实现功能点层分析
6. 实现骨架层和测试骨架层
7. 增加 flows / features / skeletons / unknowns 的 Markdown 导出
8. 基于 `project_memory` 推进 HarmonyOS 实现骨架生成

## 当前风险

### 1. 过早抽象为通用 builder

风险：

- 会削弱真实项目驱动
- 会拉高 schema 和 prompt 设计难度

当前策略：

- 先围绕 Wikipedia Android 项目收敛
- 在该样板稳定后再抽象 Android / iOS / Flutter 等源工程适配层

### 2. 让模型“一次做完整 app”

风险：

- 更容易漂移
- 更难审查
- 更难发现遗漏

当前策略：

- 每一层全量覆盖
- 分层推进

### 3. 只做 Markdown，不做结构化事实源

风险：

- 难以续跑
- 难以复查 unknown
- 难以支撑后续 TDD 实现

当前策略：

- 结构化 memory 优先
- Markdown 作为导出层
