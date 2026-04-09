# 记忆存储模块

## 概述

当前仓库已经实现两层运行时记忆：

- Session Memory
- Chat Memory

它们解决的是“对话如何恢复与延续”的问题。

但按照当前产品目标，后续还需要第三层：

- Project Memory

它解决的是“迁移分析结果如何成为多会话共享的事实源”的问题。

本文件先说明当前已实现的两层记忆，并明确它们与 `project_memory/` 的边界。当前约定中，`project_memory` 默认落在目标鸿蒙工程下的 `.migration/project_memory/`，而不是当前 agent 仓库根目录。

## 三层记忆的职责边界

### 1. Session Memory

作用：

- 保存单次 session 的原始消息
- 支持恢复同一次执行上下文

特点：

- 颗粒度最细
- 信息完整但噪声大
- 适合追溯对话，不适合作为工程事实源

### 2. Chat Memory

作用：

- 聚合同一个 chat 下的多个 session
- 保存标题、摘要和关联关系

特点：

- 用于长期对话延续
- 能减少每次从头解释背景的成本
- 仍然不适合作为迁移工程 roadmap

### 3. Project Memory（规划中）

作用：

- 存放迁移分析的结构化产物
- 保存模块、页面、流程、功能点、unknown、实现骨架、测试骨架等事实
- 作为后续多会话实现的唯一 roadmap

特点：

- 以结构化工程状态为主，不保存聊天原文
- 可被后续 agent 稳定消费
- 要支持版本化、增量更新、导出和恢复继续

## 当前已实现模块

### 1. SessionMemory 类 (`agent/memory.py`)

负责会话原始消息的存储、加载以及会话摘要管理。

#### 存储结构

- `storage_path/raw/`：原始会话消息，文件名 `{session_id}.json`
- `storage_path/summaries/`：会话摘要，文件名 `{session_id}.json`

#### 主要方法

- `__init__(storage_path)`
- `save_session(session_id, messages)`
- `load_session(session_id)`
- `delete_session(session_id)`
- `save_session_summary(session_id, summary_data)`
- `load_session_summary(session_id)`
- `list_session_summaries(session_ids)`

#### 原始会话格式示例

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "updated_at": "2024-03-24T13:47:24.069405",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

#### 会话摘要格式示例

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Wikipedia 迁移分析：模块层初扫",
  "summary": "本次 session 完成了 Android 工程模块扫描，发现若干待确认依赖和 UI 容器边界。",
  "updated_at": "2024-03-24T13:47:24.069405"
}
```

### 2. ChatMemory 类 (`agent/chat_memory.py`)

负责聊天级元数据管理，一个 chat 可包含多个 session。

#### 存储结构

- `chat_storage_path/meta/`：聊天元数据，文件名 `{chat_id}.json`

#### 主要方法

- `__init__(chat_storage_path, session_storage_path)`
- `create_chat()`
- `save_chat_meta(chat_id, meta)`
- `load_chat_meta(chat_id)`
- `add_session_to_chat(chat_id, session_id)`
- `get_latest_chat()`
- `list_recent_chat_meta(limit)`
- `list_chats()`
- `get_chat_sessions(chat_id)`

#### 聊天元数据格式示例

```json
{
  "chat_id": "bc19ef42-43c3-4484-be53-cd6c7c632ac1",
  "title": "Wikipedia 迁移分析闭环",
  "summary": "围绕 Android Wikipedia 项目的模块、页面、功能点和 unknown 收敛持续推进。",
  "session_ids": [
    "c35f6138-0e83-497b-9948-d9267e6584ca",
    "aba18309-64fa-43db-bfde-a777fed10b1a"
  ],
  "created_at": "2024-03-24T13:47:24.069405",
  "updated_at": "2024-03-24T14:20:10.123456"
}
```

### 3. AgentLoop 集成 (`agent/loop.py`)

当前 `AgentLoop` 已完成：

- 初始化 `SessionMemory` 和 `ChatMemory`
- 在 `start_session()` 时注入当前 chat 摘要
- 支持 session 恢复、chat 恢复和多 session 合并
- 运行过程中保存会话

这为后续 `project_memory` 打下了运行时基础，但不等于已经具备迁移分析事实存储。

## 当前配置项

在 `config.json` 的 `agent` 部分：

```json
{
  "agent": {
    "session_storage_path": "./sessions",
    "chat_storage_path": "./chats"
  }
}
```

## 下一阶段需要补什么

为适配当前产品目标，下一阶段需要新增第三层存储：

### 1. 新增目标工程内的 `project_memory/`

建议存放：

- `builder_job.json`
- `project_overview.json`
- 索引类产物
- unknown 队列
- 实现骨架与测试骨架
- 导出 manifest

默认位置：

- `<target-harmony-project>/.migration/project_memory/`

### 2. 明确与 chat/session 的关系

- Session / Chat：保存交流过程
- Project Memory：保存迁移事实和 roadmap

它们必须并存，但不能混用。

### 3. 支持多会话续跑

后续实现会拆成多个会话，`project_memory` 必须能让新会话快速恢复到统一工程状态，而不是依赖阅读大量历史聊天记录。

## 注意事项

1. 当前 `SessionMemory` 和 `ChatMemory` 已可用于恢复对话，但不能替代 `project_memory/`。
2. 后续 `project_memory/` 应避免保存冗长 chat 文本，优先保存结构化事实、证据索引和状态字段。
3. 如果未来引入多进程并发分析，文件级存储需要额外的锁或乐观并发控制。
