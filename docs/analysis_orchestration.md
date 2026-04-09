# 分层分析阶段机与 Unknown 管理机制

## 目标

本文件定义 MVP-1 的两个核心机制：

- 分层分析阶段机
- unknown 评分、筛选、复查和人工确认机制

没有这两部分，系统只能停留在“会探索代码库的聊天 agent”，不能成为可持续续跑的迁移分析 orchestrator。

## 一、阶段机设计

## 1. 总体原则

- 按层推进，不跨层乱跳
- 每一层都要求当前层全量覆盖
- 每层结束后必须做覆盖校验和 unknown 回收
- 高风险 unknown 可中断当前阶段，但中断后必须能恢复

## 2. 阶段列表

建议使用以下阶段：

1. `bootstrap_job`
2. `analyze_modules`
3. `analyze_pages`
4. `analyze_flows`
5. `analyze_features`
6. `analyze_implementation_skeleton`
7. `analyze_test_skeleton`
8. `unknowns_recheck`
9. `export_docs`
10. `completed`

## 3. 各阶段职责

### 3.1 `bootstrap_job`

输入：

- Android 源工程路径
- HarmonyOS template 路径
- 当前配置与阈值

输出：

- `builder_job.json`
- `project_overview.json` 初稿

准出条件：

- 路径有效
- 基本任务合同已落盘

### 3.2 `analyze_modules`

目标：

- 全量识别模块边界、共享层、基础设施层和业务层

输出：

- `module_index.json`
- 初步 evidence
- 初步 unknown

准出条件：

- 模块层无明显未分类大块区域
- 关键模块有 evidence

### 3.3 `analyze_pages`

目标：

- 找出页面、入口、容器、导航组织关系

输出：

- `page_index.json`
- `module -> page` 映射

准出条件：

- 主要页面可回溯到模块
- 页面级 unknown 已入队

### 3.4 `analyze_flows`

目标：

- 识别核心用户流程和页面序列

输出：

- `flow_index.json`
- `page -> flow` 映射

准出条件：

- 主要用户流程有清晰触发点和页面序列

### 3.5 `analyze_features`

目标：

- 以功能点视角做最终防漏

输出：

- `feature_index.json`
- `flow -> feature` 映射

准出条件：

- 关键 feature 均有来源证据
- 模块、页面、流程、功能点四视图已可交叉验证

### 3.6 `analyze_implementation_skeleton`

目标：

- 把分析结果落到文件、类、方法和行为契约

输出：

- `file_index.json`
- `implementation_index.json`

准出条件：

- 关键 feature 至少映射到实现文件或明确 gap

### 3.7 `analyze_test_skeleton`

目标：

- 生成后续 TDD 可直接使用的测试入口

输出：

- `test_index.json`

准出条件：

- 关键实现骨架具备对应测试入口

### 3.8 `unknowns_recheck`

目标：

- 带着全部未关闭 unknown 重新复查一次

输出：

- 更新 `unknowns/queue.json`
- 更新 `unknowns/final_gaps.json`

准出条件：

- 所有未关闭 unknown 至少复查过一轮
- 最终 gap 为“复查后仍无法确认”的剩余项

### 3.9 `export_docs`

目标：

- 把结构化 memory 导出为高可读文档

输出：

- `exports/*.md`
- `export_manifest.json`

准出条件：

- 导出内容和结构化 memory 一致

## 4. 阶段流转规则

标准流转：

```text
bootstrap_job
  -> analyze_modules
  -> analyze_pages
  -> analyze_flows
  -> analyze_features
  -> analyze_implementation_skeleton
  -> analyze_test_skeleton
  -> unknowns_recheck
  -> export_docs
  -> completed
```

允许中断点：

- 任意分析阶段遇到高风险 unknown

中断后状态：

- `paused_for_confirmation`

恢复规则：

- 用户完成确认项清单后，从当前阶段继续
- 不回退到 `bootstrap_job`

## 二、Unknown 管理机制

## 1. 设计目标

unknown 不是“最后才整理的问题列表”，而是贯穿全流程的跟踪对象。

它必须支持：

- 早发现
- 持续携带
- 后续复查
- 条件化人工确认
- 最终 gap 收口

## 2. unknown 生命周期

建议状态：

- `open`
- `in_review`
- `needs_user_confirmation`
- `resolved`
- `converted_to_gap`

生命周期：

```text
发现 unknown
  -> 写入 queue
  -> 后续阶段持续带着分析
  -> 若证据足够则 resolved
  -> 若评分过阈值则 needs_user_confirmation
  -> 若全量分析 + 复查后仍无答案，则 converted_to_gap
```

## 3. 双评分机制

每个 unknown 至少需要两种分数：

- `uncertainty_score`
- `severity_score`

解释：

- `uncertainty_score`：当前信息不足的程度
- `severity_score`：如果判断错了，对迁移结果的影响程度

建议同时计算一个综合决策分：

```text
decision_score = max(uncertainty_score, severity_score)
```

也可以后续换成加权算法，但 MVP-1 先用简单规则，利于解释。

## 4. 阈值与筛选

默认策略：

- `decision_score < threshold`：agent 可自治处理，但必须写入决策记录
- `decision_score >= threshold`：进入待确认项清单

默认阈值：

- `60`

要求：

- 阈值可运行时调整
- 单次确认项清单最多 `10` 条

## 5. 人工确认触发条件

不仅看分数，还看影响类型。

即使分数不高，只要 unknown 可能导致：

- 主流程页面判断错误
- 关键依赖方向选错
- 模块边界严重偏差
- 骨架文件规划错误

也允许提升为人工确认项。

## 6. 待确认项清单格式

每项至少包含：

- 问题描述
- 证据来源
- 候选方案
- 推荐项
- 影响范围
- 若不确认会阻塞什么
- `uncertainty_score`
- `severity_score`
- `decision_score`

这份清单应成为用户与系统之间的主要沟通通道。

## 7. 复查规则

所有仍处于 `open` 或 `in_review` 的 unknown，在最终输出 gap 前必须至少复查一轮。

复查要求：

- 带着问题重新扫描相关证据
- 允许跨层回查
- 若能确认，则关闭 unknown
- 若仍不能确认，再转为最终 gap

不允许跳过复查直接输出 final gap。

## 8. agent 自治决策规则

当 unknown 低于阈值时，agent 可自行选择方案，但必须：

- 记录为什么这样选
- 记录依据来源
- 记录此决策是否可被后续推翻
- 记录是否使用 mock

这样可以让后续会话理解“为什么之前这么做”。

## 9. mock 决策规则

当依赖链不清，但用户目标是优先打通前端页面与业务流程时，可允许 mock。

mock 决策至少要记录：

- mock 的对象
- mock 的原因
- mock 覆盖哪些页面或流程
- 真正依赖尚缺什么
- 后续回填条件

## 三、对 `qwen` 的执行约束

在每一阶段，`qwen` 的输出不应是自由文本总结，而应是结构化分析结果，至少包含：

- 已确认结论
- 证据
- 未覆盖区域
- 新发现 unknown
- 建议下一步

主 orchestrator 需要根据这些内容决定：

- 接受
- 打回补充
- 改 prompt 重试
- 暂停并请求用户确认

## 四、MVP-1 验收重点

如果以下任一项做不到，阶段机和 unknown 机制就还不合格：

- 不能从中断点继续
- unknown 没有被持续带入后续分析
- 最终 gap 没经过复查
- 低风险 unknown 的自治决策没有记录依据
- 高风险 unknown 没有形成可操作的确认清单
- 每一层结束后没有做覆盖校验
