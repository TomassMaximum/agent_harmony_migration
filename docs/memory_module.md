# 记忆存储模块

## 概述

本模块为迁移助手（Agent）提供了两层记忆存储：会话级（Session）和聊天级（Chat）。通过将会话消息和聊天元数据保存到本地文件系统，实现了对话的连续性、可恢复性以及跨会话的上下文管理。

## 模块组成

### 1. SessionMemory 类 (`agent/memory.py`)

负责会话原始消息的存储、加载以及会话摘要的管理。

#### 存储结构

- `storage_path/raw/`：存放原始会话消息，文件名为 `{session_id}.json`。
- `storage_path/summaries/`：存放会话摘要，文件名为 `{session_id}.json`。

#### 主要方法

- `__init__(storage_path)`: 初始化存储目录，创建 raw 和 summaries 子目录。
- `save_session(session_id, messages)`: 保存会话原始消息到 raw 目录。
- `load_session(session_id)`: 从 raw 目录加载会话消息，返回 Message 列表（若无则返回空列表）。
- `delete_session(session_id)`: 删除该会话的原始文件和摘要文件。
- `save_session_summary(session_id, summary_data)`: 保存会话摘要到 summaries 目录。
- `load_session_summary(session_id)`: 加载会话摘要，返回字典或 None。
- `list_session_summaries(session_ids)`: 列出给定会话ID的摘要列表，若无则扫描 summaries 目录。

#### 存储格式示例

**原始会话文件** (`raw/{session_id}.json`):
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

**会话摘要文件** (`summaries/{session_id}.json`):
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "工程迁移助手自检：探索项目结构与功能",
  "summary": "助手执行了自检任务，通过逐步探索项目根目录和关键文件，了解了工程的基本结构和功能...",
  "updated_at": "2024-03-24T13:47:24.069405"
}
```

### 2. ChatMemory 类 (`agent/chat_memory.py`)

负责聊天（chat）的元数据管理，一个聊天可以包含多个会话（session）。

#### 存储结构

- `chat_storage_path/meta/`：存放聊天元数据，文件名为 `{chat_id}.json`。

#### 主要方法

- `__init__(chat_storage_path, session_storage_path)`: 初始化存储目录。
- `create_chat()`: 创建新聊天，返回 chat_id。
- `save_chat_meta(chat_id, meta)`: 保存或更新聊天元数据。
- `load_chat_meta(chat_id)`: 加载聊天元数据。
- `add_session_to_chat(chat_id, session_id)`: 将会话关联到聊天。
- `get_latest_chat()`: 获取最近使用的聊天ID。
- `list_recent_chat_meta(limit)`: 按更新时间倒序列出聊天元数据。
- `list_chats()`: 列出所有聊天ID。
- `get_chat_sessions(chat_id)`: 获取该聊天下的所有会话ID列表。

#### 聊天元数据格式

```json
{
  "chat_id": "bc19ef42-43c3-4484-be53-cd6c7c632ac1",
  "title": "工程迁移助手系统自检与功能探索",
  "summary": "本次对话围绕工程迁移助手系统的自检与功能探索展开...",
  "session_ids": ["c35f6138-0e83-497b-9948-d9267e6584ca", "aba18309-64fa-43db-bfde-a777fed10b1a"],
  "created_at": "2024-03-24T13:47:24.069405",
  "updated_at": "2024-03-24T14:20:10.123456"
}
```

### 3. AgentLoop 集成 (`agent/loop.py`)

#### 初始化

- `__init__` 中创建 `SessionMemory` 和 `ChatMemory` 实例。
- 支持传入 `session_id` 和 `chat_id`，若不提供则自动生成（session_id）或使用最近聊天（chat_id）。

#### 记忆注入

- `_build_current_chat_memory_block()`: 构建当前聊天的记忆块，包含聊天标题、摘要以及下属会话的摘要列表。该块在 `start_session` 时作为系统消息注入，提供上下文记忆。

#### 会话生命周期

- `start_session(load_existing, inject_current_chat_memory)`: 启动会话时，若 `load_existing` 为 True 且会话存在，则加载历史消息；若 `inject_current_chat_memory` 为 True，则注入聊天记忆块。
- `save_session()`: 保存当前会话原始消息，并将会话关联到当前聊天。
- `load_session(session_id)`: 加载指定会话，并更新当前会话ID和消息。
- `send_user_message()`: 自动调用 `save_session()` 保存。

#### 摘要生成

- `_build_session_summary()`: 使用 LLM 生成会话摘要（标题和总结），保存到 `SessionMemory` 的 summaries 目录。
- 摘要可用于后续记忆块注入，减少原始消息的长度。

### 4. 配置项

在 `config.json` 的 `agent` 部分：

```json
{
  "agent": {
    "session_storage_path": "./sessions",
    "chat_storage_path": "./chats"
  }
}
```

## 使用示例

### 1. 命令行使用

```python
from agent.loop import AgentLoop

# 创建新聊天（自动）和新会话
agent = AgentLoop()
print(f"Chat ID: {agent.chat_id}, Session ID: {agent.session_id}")
agent.start_session("探索工程")

# 进行对话
agent.send_user_message("列出根目录")

# 手动保存
agent.save_session()

# 恢复会话（新实例）
agent2 = AgentLoop(session_id=agent.session_id, chat_id=agent.chat_id)
agent2.start_session("", load_existing=True)  # 加载历史消息

# 查看当前聊天的记忆
memory_block = agent2._build_current_chat_memory_block()
print(memory_block)
```

### 2. Web接口（参考）

Web 接口应支持聊天和会话两层管理，具体实现请参考 `web_agent.py`（如有）。

#### 初始化新聊天

```bash
curl -X POST http://localhost:5001/init \
  -H "Content-Type: application/json" \
  -d '{}'
```

#### 恢复现有聊天/会话

```bash
curl -X POST http://localhost:5001/init \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "bc19ef42-43c3-4484-be53-cd6c7c632ac1",
    "session_id": "c35f6138-0e83-497b-9948-d9267e6584ca"
  }'
```

#### 发送消息

```bash
curl -X POST http://localhost:5001/chat \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "bc19ef42-43c3-4484-be53-cd6c7c632ac1",
    "session_id": "c35f6138-0e83-497b-9948-d9267e6584ca",
    "message": "列出根目录"
  }'
```

#### 列出所有聊天

```bash
curl http://localhost:5001/list_chats
```

#### 列出某个聊天的会话

```bash
curl http://localhost:5001/list_sessions?chat_id=bc19ef42-43c3-4484-be53-cd6c7c632ac1
```

## 注意事项

1. **并发安全**：AgentLoop 内部使用线程锁，但多进程部署时文件存储可能需额外锁机制。
2. **性能影响**：频繁保存可能影响性能，可根据对话频率调整保存策略。
3. **存储空间**：监控存储目录大小，避免无限增长。
4. **摘要生成依赖 LLM**：需要配置有效的 LLM API 密钥，否则摘要功能可能失败。
