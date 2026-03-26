# 开发路线图

## 当前判断

项目已完成里程碑 1，当前处于“底座收口完成，准备进入结构化迁移能力建设”的阶段。

当前底座已经具备：

- 统一的执行主干：`run_until_stop()` / `_iter_until_stop()`
- 两个正式入口：
  - `scripts/chat_agent.py`
  - `scripts/openai_adapter.py`
- 统一的停止原因、事件协议和 trace 渲染
- 会话与 chat 记忆
- 基础权限阻断
- 配置入口与运行说明
- 基线测试

## 里程碑 1 状态

里程碑 1 目标：把“能跑但不够稳定”的原型收口成一个可靠的代理底座。

当前状态：已完成

已完成任务：

- `M1-T1` 修复执行主干断点
- `M1-T2` 统一 AgentLoop 执行语义
- `M1-T3` 梳理 CLI / Web 两类入口职责边界
- `M1-T4` 统一事件协议与可观察性
- `M1-T5` 补齐最小测试基线
- `M1-T6` 收口权限策略
- `M1-T7` 收口错误模型与停止原因
- `M1-T8` 整理配置与运行方式

里程碑 1 完成后的结果：

- 交互式 CLI 与 Web 入口都可用
- 停止原因已统一为结构化结果
- 权限阻塞已接入正式执行链路
- 提示词入口已统一到 `agent/prompts.py`
- 当前入口、配置、trace、测试都已收口

相关文档：

- 运行与配置：[runtime_config.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/runtime_config.md)
- 基线测试：[testing_baseline.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/testing_baseline.md)
- MVP 目标：[MVP_minimum.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/MVP_minimum.md)

## 下一阶段

### 里程碑 2：结构化工程记忆

目标：
从“chat/session 记忆”升级到“工程状态记忆”，开始落地结构化产物。

建议交付：

- `project_memory/`
- `project_overview.json`
- 结构化 schema
- 工程状态恢复机制

完成标准：

- Analyze 阶段可产出并复用结构化工程概览
- 重启后可从产物恢复状态，而不是只靠聊天上下文

### 里程碑 3：分阶段 orchestrator

目标：
把当前通用 agent 升级为 `Analyze -> Design -> Implement -> Review` 的流程化系统。

建议交付：

- 阶段编排器
- 分阶段 prompt / mode
- 阶段级约束与状态推进

完成标准：

- 系统能按阶段推进，而不是依赖模型自由决定下一步

### 里程碑 4：Harness 与验收闭环

目标：
形成最小可用迁移闭环，而不是只有分析与改代码能力。

建议交付：

- 合同测试 / 模块测试接口
- `review.json`
- `approved / rework / redesign` 决策结果

完成标准：

- 单模块可以完整走完 Design -> Implement -> Test -> Review

## 当前优先级

建议下一步直接进入里程碑 2，优先顺序如下：

1. 定义 `project_memory/` 目录与 schema
2. 落地 `project_overview.json`
3. 实现工程状态恢复
4. 为 Analyze 阶段接入结构化产物输出
