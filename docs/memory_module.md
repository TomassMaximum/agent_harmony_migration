# 会话记忆存储模块

## 概述

本模块为迁移助手（Agent）提供了会话持久化存储功能，解决了Web服务重启或会话重置时对话历史丢失的问题。通过将会话消息保存到本地文件系统，实现了对话的连续性和可恢复性。

## 设计目标

1. **会话持久化**：将会话消息（self.messages）定期保存到持久化存储中。
2. **记忆检索与加载**：支持通过会话ID恢复历史对话。
3. **轻量级实现**：使用JSON文件存储，无需额外数据库依赖。
4. **向后兼容**：不影响现有AgentLoop和Web接口的功能。

## 模块组成

### 1. SessionMemory 类 (`agent/memory.py`)

负责会话的序列化、保存和加载。

#### 主要方法

- `__init__(storage_path)`: 初始化存储目录。
- `save_session(session_id, messages, metadata)`: 保存会话到JSON文件。
- `load_session(session_id)`: 从文件加载会话消息，返回Message列表或None。
- `delete_session(session_id)`: 删除会话文件。
- `list_sessions()`: 列出所有存储的会话ID。

#### 存储格式

会话文件以 `{session_id}.json` 命名，存储在配置的 `session_storage_path` 目录下。文件内容示例：

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "metadata": {}
}
```

### 2. AgentLoop 扩展 (`agent/loop.py`)

#### 新增功能

- **会话ID支持**：`__init__` 方法新增 `session_id` 参数，若不提供则自动生成UUID。
- **记忆管理器**：内部包含 `SessionMemory` 实例。
- **自动保存**：在 `send_user_message`、`step_once`（工具执行后和最终答案后）自动调用 `save_session()`。
- **会话恢复**：`start_session` 方法新增 `load_existing` 参数，若为True且会话ID已存在存储中，则自动加载历史消息。
- **手动保存/加载**：提供 `save_session()` 和 `load_session(session_id)` 方法。

#### 配置项

在 `config.json` 的 `agent` 部分新增：

```json
"session_storage_path": "./sessions"
```

### 3. Web接口扩展 (`web_agent.py`)

#### 多会话支持

- 将全局单agent实例改为按会话ID存储的字典 `agents`。
- 每个HTTP请求需携带 `session_id` 参数（除初始化外）。

#### 新增端点

- `POST /init`: 支持传入 `session_id` 以恢复历史会话；若不提供则创建新会话。
- `POST /save_session`: 手动触发保存当前会话。
- `GET /list_sessions`: 列出所有存储的会话ID。

#### 前端适配

- 页面显示当前会话ID。
- 支持通过URL参数 `?session_id=...` 恢复特定会话。
- 所有聊天请求自动附带会话ID。

## 使用示例

### 1. 命令行使用

```python
from agent.loop import AgentLoop

# 创建新会话
agent = AgentLoop()
print(f"Session ID: {agent.session_id}")
agent.start_session("探索工程")

# 进行一些对话...
agent.send_user_message("列出根目录")

# 手动保存
agent.save_session()

# 恢复会话（新实例）
agent2 = AgentLoop(session_id=agent.session_id)
agent2.start_session("", load_existing=True)  # 加载历史消息
```

### 2. Web接口

#### 初始化新会话

```bash
curl -X POST http://localhost:5001/init \
  -H "Content-Type: application/json" \
  -d '{}'
```

响应：
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "会话已初始化"
}
```

#### 恢复现有会话

```bash
curl -X POST http://localhost:5001/init \
  -H "Content-Type: application/json" \
  -d '{"session_id": "550e8400-e29b-41d4-a716-446655440000"}'
```

#### 发送消息

```bash
curl -X POST http://localhost:5001/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "列出根目录"
  }'
```

#### 手动保存

```bash
curl -X POST http://localhost:5001/save_session \
  -H "Content-Type: application/json" \
  -d '{"session_id": "550e8400-e29b-41d4-a716-446655440000"}'
```

#### 列出所有会话

```bash
curl http://localhost:5001/list_sessions
```

## 配置说明

### 默认配置

```json
{
  "agent": {
    "session_storage_path": "./sessions"
  }
}
```

### 自定义存储路径

修改 `config.json`，将 `session_storage_path` 设置为任意有效目录路径（绝对或相对）。

## 扩展建议

### 1. 记忆摘要与压缩

对于长对话，可定期使用LLM生成会话摘要，替换部分旧消息，以节省上下文窗口。

实现思路：
- 在 `SessionMemory.save_session` 中添加摘要生成逻辑（例如每10条消息）。
- 将摘要保存在 `metadata` 字段中。
- 加载会话时，可将摘要作为系统提示的一部分注入。

### 2. 存储后端扩展

当前使用文件系统存储，可扩展支持：
- SQLite数据库
- Redis（用于分布式部署）
- 云存储（如S3）

只需实现新的存储类，保持与 `SessionMemory` 相同的接口即可。

### 3. 会话清理策略

可添加自动清理机制，例如：
- 基于时间的过期删除（如30天未活跃）。
- 基于大小的限制（如最多保留100个会话）。

## 注意事项

1. **并发安全**：AgentLoop内部使用线程锁，但多进程部署时文件存储可能需额外锁机制。
2. **性能影响**：频繁保存可能影响性能，可根据对话频率调整保存策略（如每N条消息保存一次）。
3. **存储空间**：监控会话目录大小，避免无限增长。

## 总结

本存储模块以最小侵入性为Agent添加了记忆功能，确保了对话的连续性和可恢复性，为长期协作任务提供了基础支持。
