鸿蒙迁移 Agent 最小可用架构设计（MVP）
一、背景与目标
1.1 背景

当前目标是构建一个 鸿蒙 App 迁移 Agent，用于将 Android / iOS / Flutter 等项目迁移到 HarmonyOS（ArkTS）平台。

传统 Agent 存在的问题：

上下文过大 → 输出不稳定
分析与实现混在一起 → 容易走偏
无法持续记忆工程状态 → 每次从头理解
缺乏验收机制 → 结果不可控
1.2 设计目标

本系统目标：

控制上下文规模，提升稳定性
分阶段推进（分析 → 设计 → 实现 → 验收）
引入 Contract + Test 机制保证正确性
构建结构化工程记忆（非 chat 记忆）
支持失败回退与重新设计
二、总体架构
2.1 核心组件

系统由 4 个核心组件组成：

组件	职责
Orchestrator	调度流程、控制阶段、决策流转
Artifact Store	存储结构化工程记忆
Worker Modes	不同阶段的 LLM 执行模式
Harness	测试执行与结果验证
2.2 架构关系
User Input
    ↓
Orchestrator
    ↓
Worker Mode (LLM)
    ↓
Artifact Store（写入）
    ↓
Harness（执行测试）
    ↓
Orchestrator（决策）
三、阶段划分（MVP）

系统划分为 4 个阶段：

Phase 1：Project Analyze（全局分析）
输入：
原工程路径
目标工程路径
输出：
project_overview.json
职责：
判断项目类型（Android / Flutter 等）
识别目录结构
拆分一级模块
识别风险
限制：
❌ 不允许修改代码
Phase 2：Module Design（模块设计）
输入：
project_overview
相关源码（最小必要）
输出：
modules/<module>/design.json
职责：
定义模块职责
定义接口（Contract）
定义依赖
定义验收标准（Test Spec）
限制：
❌ 不允许修改代码
Phase 3：Module Implement（模块实现）
输入：
module design
必要源代码
输出：
代码修改
implementation.json
职责：
实现模块逻辑
自检
标记问题
Phase 4：Module Review（模块验收）
输入：
design
implementation
测试结果
diff
输出：
review.json
决策：
✅ approved
🔁 rework
🧠 redesign
四、核心数据结构（Schema）
4.1 Project Overview
{
  "project_name": "",
  "source_platform": "",
  "target_platform": "HarmonyOS ArkTS",
  "source_project_path": "",
  "target_project_path": "",
  "high_level_summary": "",
  "module_list": [
    {
      "name": "",
      "type": "infrastructure | business | shared",
      "description": "",
      "priority": 0
    }
  ],
  "global_risks": [],
  "current_stage": "analyze | design | implement | review"
}
4.2 Module Design（核心 Contract）
{
  "module_name": "",
  "responsibility": "",
  "inputs": [],
  "outputs": [],
  "public_interfaces": [
    {
      "name": "",
      "signature": "",
      "expected_behavior": "",
      "error_behavior": ""
    }
  ],
  "dependencies": [],
  "target_files": [],
  "acceptance_criteria": [],
  "notes": []
}
4.3 Implementation Report
{
  "module_name": "",
  "based_on_design": "",
  "modified_files": [],
  "implemented_interfaces": [],
  "self_check_summary": "",
  "known_issues": [],
  "status": "done | partial | blocked"
}
4.4 Review Result
{
  "module_name": "",
  "review_input": {
    "design_version": "",
    "implementation_version": ""
  },
  "test_result": "pass | fail | partial",
  "contract_match": true,
  "issues": [],
  "decision": "approved | rework | redesign",
  "next_action": ""
}
五、Worker Modes（角色模式）

统一使用一个模型，通过不同模式控制行为：

Mode	职责
analyze_mode	工程结构分析
design_mode	模块设计
implement_mode	代码实现
review_mode	验收决策
六、Harness（测试系统）
6.1 职责
执行测试
收集日志
比对结果
输出结构化结果
6.2 测试分层
1. Contract Test
方法输入/输出正确性
2. Module Test
模块逻辑闭环
3. Integration Test（后续阶段）
跨模块协作
七、核心流程（单模块）
Analyze（全局）
    ↓
Select Module
    ↓
Design Module
    ↓
Implement Module
    ↓
Run Tests (Harness)
    ↓
Review
    ↓
[通过] → 下一模块
[失败] → Rework / Redesign
八、关键约束（必须遵守）
8.1 分阶段约束
阶段	是否允许改代码
Analyze	❌
Design	❌
Implement	✅
Review	❌
8.2 Contract 不可下层修改

实现层：

❌ 不允许修改接口定义
❌ 不允许修改测试预期
✅ 只能实现或上报问题
8.3 单模块执行原则

同一时间只允许一个模块进入实现阶段

优势：

控制复杂度
易调试
易回滚
九、工程记忆（Artifact Store）
9.1 存储结构
project_memory/
  project_overview.json
  modules/
    network/
      design.json
      implementation.json
      review.json
9.2 设计原则
不存 chat history
只存结构化工程状态
每个阶段产出即记忆
十、最小实现顺序（推荐）
✅ 实现 project_overview 生成
✅ 实现 module design
✅ 实现 implement → review 闭环
✅ orchestrator 控制流程
十一、设计原则总结
核心原则
上下文最小化
分阶段执行
Contract 驱动
测试约束
单模块推进
一句话总结

不是让一个 Agent 记住所有事情，而是让系统通过分层产物和测试约束，逐步收敛工程的正确状态。

十二、后续扩展（非 MVP）

后续可以逐步增加：

Decision Log（决策记录）
Feedback Ticket（设计反馈）
多模块并行（受控）
失败 Case 学习
Agent 多角色拆分