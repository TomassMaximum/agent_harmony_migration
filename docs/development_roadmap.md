# 开发路线图

## 当前判断

当前仓库已经完成里程碑 1：运行底座收口。

已具备：

- `AgentLoop`
- 工具注册与 trace
- chat / session 记忆
- 最小权限机制
- CLI / Web 入口
- 基线测试

但还没有进入迁移分析 orchestrator 的产品闭环。

## 路线原则

- 先把一个真实项目跑通，再抽象通用能力
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

这是当前最优先里程碑。

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

## 当前应做的两件事

### 1. 定稿 `project_memory` schema 和目录结构

必须先定义：

- 根目录结构
- 核心索引
- unknown 数据结构
- skeleton 数据结构
- 导出 manifest

没有这一步，后续所有分析结果都只能停留在聊天文本里。

### 2. 定稿阶段机和 unknown 机制

必须先定义：

- 各层分析阶段
- 每层准入 / 准出条件
- unknown 的评分、筛选和复查规则
- 何时暂停、何时继续、何时抛出最终 gap

没有这一步，系统无法稳定续跑，也无法控制人工介入点。

## 近期开发顺序

建议顺序如下：

1. 文档统一到当前产品定位
2. 定义 `project_memory` schema 和目录结构
3. 定义阶段机与 unknown 机制
4. 为 schema、阶段机和恢复继续补测试
5. 实现最小可运行的迁移分析闭环
6. 增加 Markdown 导出能力

## 当前风险

### 1. 过早抽象为通用 builder

风险：

- 会削弱真实项目驱动
- 会拉高 schema 和 prompt 设计难度

当前策略：

- 先围绕 Wikipedia Android 项目收敛

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
