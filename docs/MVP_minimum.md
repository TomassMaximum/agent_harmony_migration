# App -> HarmonyOS 迁移 Agent MVP（MVP-1）

## 0. 最终产品愿景

最终产品形态是一个面向移动端源码工程的 `source app -> HarmonyOS` 迁移 agent。

长期目标不是只能迁移当前 Wikipedia Android 项目，也不是只能服务 Android。用户应能把源工程替换为 Android、iOS、Flutter 或其它移动端项目，并向 agent 下达一条迁移指令；agent 负责完成项目识别、分层分析、差异建模、目标鸿蒙工程规划、代码迁移、构建修复、测试推进和 gap 收敛，最终交付可编译、可运行、主要功能页面可达的 HarmonyOS 工程，或至少完成大部分可自动化迁移工作并清晰列出剩余人工 gap。

当前 MVP-1 选择 Wikipedia Android 作为唯一验证样板，是为了先把迁移分析、`project memory`、unknown 管理和多会话续跑闭环跑扎实。这个固定项目边界是阶段策略，不是最终产品边界。

## 1. 产品定位

当前产品不是通用工程问题 agent builder，也不是直接交付完整 HarmonyOS 业务代码的全自动迁移器。

当前 MVP-1 的准确定位是：

一个围绕固定 Android 项目运行的迁移分析 orchestrator。

它的职责是：

- 驱动 `qwen` 对源工程做分层、全量分析
- 把分析结果沉淀为结构化 `project memory`
- 管理 unknown / gap 的持续跟踪与复查
- 在关键阻塞点暂停并输出待确认项清单
- 为后续多会话、TDD 驱动的真正迁移实现和多源工程泛化提供 roadmap

## 2. 当前目标项目

MVP-1 只服务一个固定项目，不追求一开始就通用：

- Android 源工程：
  `/Users/weibaoping/Android/opensource/wikipedia-android/apps-android-wikipedia/`
- HarmonyOS template 工程：
  `/Users/weibaoping/ohos/migrate/wiki/`

这个选择是产品策略，不是临时妥协。先把一个真实项目迁移分析做扎实，再抽象可复用能力和多源工程适配层，风险最低。

## 3. 用户与交付目标

当前用户是单个开发者本人。

用户真正需要的不是“聊完一次就结束的分析答案”，而是：

- 一个能稳定继续任务的迁移分析系统
- 一个不会因为多次会话而漂移的事实源
- 一个能逐步把分析推进到实现骨架层的 roadmap

最终长期目标仍然是：

- 支持 Android、iOS、Flutter 等源项目迁移到 HarmonyOS
- 产出可编译、可运行、主要功能页面可达的 HarmonyOS 工程
- 自动完成大部分可迁移代码、构建修复和测试推进
- 最终提供清晰、高可读性的交付文档

但 `MVP-1` 本身不要求完成真正的迁移实现。

## 4. MVP-1 交付物

MVP-1 必须稳定交付以下产物：

- 目标鸿蒙工程内的 `project_memory/` 结构化目录
- 模块层、页面层、流程层、功能点层的索引与映射
- 实现层骨架：
  - 目标文件清单
  - 类/方法签名
  - 行为契约
  - 测试入口
  - mock 决策点
- unknown / gap 跟踪队列
- 待确认项清单
- Markdown 导出文档

## 5. 产品原则

### 5.1 分层推进，但每层都要求全量覆盖

不是“一轮做整个 app 的全量”，而是：

- 模块层全量覆盖
- 页面层全量覆盖
- 流程层全量覆盖
- 实现骨架层全量覆盖

每一层结束后都必须做覆盖校验，再进入下一层。

### 5.2 防漏优先级高于美观和速度

不能接受遗漏业务功能。

覆盖必须同时从三套视角交叉验证：

- 模块
- 页面 / 用户流程
- 功能点

只有三者相互映射后，才可判定覆盖基本完整。

### 5.3 `project memory` 是事实源

开发过程中优先机器可消费、可续跑的结构化产物。

默认存放位置：

- `<target-harmony-project>/.migration/project_memory/`

Markdown 文档只用于：

- 交付展示
- 快速审阅
- 对外沟通

它不是后续实现的主事实源。

### 5.4 unknown 必须显式跟踪

一旦发现不确定项：

- 立即写入 unknown 队列
- 带着问题进入后续层次继续分析
- 若后续证据足够，则消解并关闭
- 若全项目分析完成后仍无法确认，再进入最终 gap

不允许伪确定，也不允许把早期 unknown 直接遗留到最终结果而不复查。

### 5.5 高风险项才触发人工确认

系统默认自动推进。

只有当 unknown 的不确定度或风险达到阈值，且可能造成：

- 后续实现阻塞
- 关键方案分歧
- 主要业务页面错误判断

才暂停并向用户抛出待确认项清单。

### 5.6 允许 mock，但必须留下决策痕迹

当依赖链不明时，优先保证前端业务流程可达。

经用户确认后，允许：

- 用 mock 数据
- 用 mock 服务
- 用占位能力替代未确认依赖

但必须在 memory 中记录：

- 为什么可以 mock
- mock 覆盖了什么
- 后续必须回填什么

## 6. `qwen` 在系统中的角色

`qwen` 当前承担：

- 分析执行
- 初步拆解
- 骨架化输出

主 orchestrator 的职责是：

- 下发分层任务
- 审查输出是否覆盖完整
- 根据缺陷调整 prompt
- 决定是否打回、重试或进入下一层

换句话说，`qwen` 不是最终裁判，主 orchestrator 才负责质量收敛。

## 7. MVP-1 范围

### 7.1 In Scope

- 固定项目的全量分层分析
- `project_memory` 结构化沉淀
- 覆盖校验
- unknown 跟踪与复查
- 待确认项清单
- Markdown 导出

### 7.2 Out Of Scope

- 一开始支持多个 Android 项目
- 一开始支持 iOS、Flutter 等非 Android 源工程
- 一开始支持任意工程问题
- 直接产出完整 HarmonyOS 业务代码
- 完整的迁移实现闭环与回归测试闭环

## 8. MVP-1 最低可用标准

第一版“可用”至少意味着：

- 能针对 Wikipedia Android 项目跑完整个分层分析
- 能产出结构化 `project memory`
- 能以 `模块 + 页面/流程 + 功能点` 交叉校验覆盖
- 能在高风险 unknown 处暂停
- 能生成可操作的待确认项清单
- 用户确认后能继续执行，不必从头再来
- 能导出清晰 Markdown 文档
- 最细层能落到文件、类、方法、行为契约和测试入口

## 9. 从 MVP-1 到最终形态

建议分四段演进：

### 9.1 MVP-1

先把迁移分析 orchestrator 做扎实：

- memory
- 阶段机
- unknown 管理
- 导出

### 9.2 MVP-2 及以后

基于稳定的 `project memory`，继续做：

- HarmonyOS 工程骨架生成
- TDD 驱动的实现任务拆分
- 多会话实现续跑
- 可编译、可运行、主页面可达
- gap 收敛与最终交付

### 9.3 多源工程适配

在 Wikipedia Android 样板跑通后，抽象源工程适配层：

- Android 适配器：Gradle、Manifest、Activity / Fragment / Compose、资源与变体
- iOS 适配器：Xcode project、Swift / Objective-C、Storyboard / SwiftUI、路由与资源
- Flutter 适配器：pubspec、Dart、Widget tree、路由、平台通道与资源
- 统一中间事实模型：模块、页面、流程、功能点、依赖、资源、测试入口和 unknown

### 9.4 自动迁移执行闭环

最终产品需要在分析之外继续执行：

- 生成或改写 HarmonyOS ArkTS / ETS 代码
- 持续运行构建、测试和静态检查
- 根据错误自动修复并回写 `project_memory`
- 对不能自动完成的能力输出带证据、影响范围和建议方案的 final gap
- 让用户通过少量确认推动迁移继续，而不是手工重做分析

## 10. 一句话总结

当前 MVP-1 的核心不是“让一个模型一次性迁完 App”，而是“先让系统围绕固定项目，稳定地产出不漏业务、可持续续跑、可驱动后续实现的迁移 project memory”；最终产品则要演进成可替换源项目、可迁移 Android / iOS / Flutter 到 HarmonyOS 的自动化迁移 agent。
