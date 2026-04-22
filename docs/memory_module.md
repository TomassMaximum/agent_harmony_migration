# 记忆存储模块

## 概述

当前仓库已经实现三层记忆中的前两层运行时记忆，并已落地第三层 `Project Memory` 的基础存储：

- Session Memory
- Chat Memory

它们解决的是“对话如何恢复与延续”的问题。

`Project Memory` 解决的是“迁移分析结果如何成为多会话共享的事实源”的问题。当前约定中，`project_memory` 默认落在目标鸿蒙工程下的 `.migration/project_memory/`，而不是当前 agent 仓库根目录。

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

### 3. Project Memory

作用：

- 存放迁移分析的结构化产物
- 保存模块、页面、流程、功能点、unknown、实现骨架、测试骨架等事实
- 作为后续多会话实现的唯一 roadmap

特点：

- 以结构化工程状态为主，不保存聊天原文
- 可被后续 agent 稳定消费
- 已具备基础目录初始化、JSON 读写、schema 校验、模块层/页面层产物写入、unknown 队列和 Markdown 导出
- 后续还需要补齐流程层、功能点层、实现骨架层、测试骨架层、复查和 final gap

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

### 3. ProjectMemoryStore 类 (`agent/project_memory.py`)

负责目标鸿蒙工程内迁移事实源的存储、初始化和基础校验。

#### 存储位置

- 默认位置：`<target-harmony-project>/.migration/project_memory/`
- 当前 Wikipedia 样板位置：`/Users/weibaoping/ohos/migrate/wiki/.migration/project_memory/`

#### 已初始化的核心结构

- `builder_job.json`
- `project_overview.json`
- `coverage_status.json`
- `export_manifest.json`
- `indexes/module_index.json`
- `indexes/page_index.json`
- `indexes/flow_index.json`
- `indexes/feature_index.json`
- `indexes/file_index.json`
- `indexes/evidence_index.json`
- `unknowns/queue.json`
- `unknowns/decisions.json`
- `unknowns/final_gaps.json`
- `skeletons/implementation_index.json`
- `skeletons/test_index.json`

#### 当前已有写入方

- `agent/phase1_module_analysis.py`：写入模块层、证据索引、unknown 队列和 `exports/modules.md`
- `agent/page_analysis.py`：写入页面层、合并 unknown 队列和 `exports/pages.md`
- `agent/unknown_queue.py`：读取 unknown 队列，写入确认、延后和阈值决策

### 4. AgentLoop 集成 (`agent/loop.py`)

当前 `AgentLoop` 已完成：

- 初始化 `SessionMemory` 和 `ChatMemory`
- 在 `start_session()` 时注入当前 chat 摘要
- 支持 session 恢复、chat 恢复和多 session 合并
- 运行过程中保存会话

`AgentLoop` 负责对话与工具执行，不直接替代 `Project Memory`。迁移事实源应继续写入目标鸿蒙工程内的 `.migration/project_memory/`。

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

为适配当前产品目标，下一阶段不是新增第三层存储，而是扩展已落地的 `Project Memory`：

### 1. 补齐剩余分析层

- `flow_index.json`
- `feature_index.json`
- `file_index.json`
- `implementation_index.json`
- `test_index.json`

### 2. 完善 unknown 生命周期

- 已有：队列筛选、聚合、确认、延后、阈值调整
- 待补：跨阶段复查、自治决策记录、final gap 转换

### 3. 明确与 chat/session 的关系

- Session / Chat：保存交流过程
- Project Memory：保存迁移事实和 roadmap

它们必须并存，但不能混用。

### 4. 支持多源项目迁移

长期产品形态会支持 Android、iOS、Flutter 等源项目。不同源工程适配器都应把分析结果归一写入同一套 `project_memory` schema，让后续 HarmonyOS 实现闭环不依赖源技术栈细节。

### 5. 支持多会话续跑

后续实现会拆成多个会话，`project_memory` 必须能让新会话快速恢复到统一工程状态，而不是依赖阅读大量历史聊天记录。

## 注意事项

1. 当前 `SessionMemory` 和 `ChatMemory` 已可用于恢复对话，但不能替代 `project_memory/`。
2. `project_memory/` 应避免保存冗长 chat 文本，优先保存结构化事实、证据索引和状态字段。
3. 如果未来引入多进程并发分析，文件级存储需要额外的锁或乐观并发控制。
