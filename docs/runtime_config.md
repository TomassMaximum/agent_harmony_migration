# 运行与配置说明

当前项目只保留两个入口：

- `scripts/chat_agent.py`
- `scripts/openai_adapter.py`

## 配置优先级

统一优先级如下：

1. 命令行参数
2. 环境变量
3. `config.json`
4. 代码内置默认值

说明：

- `DEEPSEEK_API_KEY` 优先级高于 `config.json` 中的 `llm.api_key`
- `chat_agent.py` 的 `--model`、`--max-steps`、`--root` 会覆盖配置文件和环境变量
- Web 入口没有命令行参数覆盖层，主要使用环境变量和 `config.json`

## config.json 分层

### `agent`

底座级配置，CLI 与 Web 共用：

- `agent.model`
- `agent.max_steps`
- `agent.root`
- `agent.session_storage_path`
- `agent.chat_storage_path`

### `llm`

模型访问配置：

- `llm.api_key`
- `llm.base_url`
- `llm.timeout`

### `tools`

工具默认参数：

- `tools.run_command.timeout`
- `tools.search_text.max_results`
- `tools.read_file.max_chars`

### `web`

仅 Web 入口使用：

- `web.host`
- `web.port`
- `web.debug`
- `web.max_steps`

### `scripts`

仅脚本入口使用：

- `scripts.chat_agent.default_max_steps`

## 环境变量映射

支持的环境变量如下：

- `HM_AGENT_MODEL` -> `agent.model`
- `HM_AGENT_MAX_STEPS` -> `agent.max_steps`
- `HM_AGENT_ROOT` -> `agent.root`
- `HM_AGENT_SESSION_STORAGE_PATH` -> `agent.session_storage_path`
- `HM_AGENT_CHAT_STORAGE_PATH` -> `agent.chat_storage_path`
- `DEEPSEEK_API_KEY` -> `llm.api_key`
- `DEEPSEEK_BASE_URL` -> `llm.base_url`
- `DEEPSEEK_TIMEOUT` -> `llm.timeout`
- `HM_AGENT_RUN_COMMAND_TIMEOUT` -> `tools.run_command.timeout`
- `HM_AGENT_SEARCH_TEXT_MAX_RESULTS` -> `tools.search_text.max_results`
- `HM_AGENT_READ_FILE_MAX_CHARS` -> `tools.read_file.max_chars`
- `HM_AGENT_WEB_HOST` -> `web.host`
- `HM_AGENT_WEB_PORT` -> `web.port`
- `HM_AGENT_WEB_DEBUG` -> `web.debug`
- `HM_AGENT_WEB_MAX_STEPS` -> `web.max_steps`
- `HM_AGENT_CHAT_MAX_STEPS` -> `scripts.chat_agent.default_max_steps`

说明：

- 布尔值支持：`true/false`、`1/0`、`yes/no`、`on/off`
- 数值型环境变量如果格式不合法，会直接报错

## 最小运行方式

### 交互式 CLI

```bash
export DEEPSEEK_API_KEY="你的 key"
python3 scripts/chat_agent.py "先分析当前工程结构"
```

可选参数：

```bash
python3 scripts/chat_agent.py "先分析当前工程结构" \
  --model deepseek-chat \
  --max-steps 120 \
  --root .
```

### Web 适配层

```bash
export DEEPSEEK_API_KEY="你的 key"
python3 scripts/openai_adapter.py
```

常用环境变量示例：

```bash
export HM_AGENT_WEB_HOST="127.0.0.1"
export HM_AGENT_WEB_PORT="5001"
export HM_AGENT_WEB_DEBUG="false"
export HM_AGENT_WEB_MAX_STEPS="12"
```

## 常见问题

### 缺少 API Key

会直接报错：

```text
未检测到 DeepSeek API Key
```

解决方式：

```bash
export DEEPSEEK_API_KEY="你的 key"
```

### 配置文件非法

如果 `config.json` 不是合法 JSON，启动时会直接报错并指出配置文件路径。

### 环境变量类型错误

例如：

- `HM_AGENT_WEB_PORT=abc`
- `HM_AGENT_WEB_DEBUG=maybe`

这类值会直接触发明确错误，而不是静默退回默认值。
