# 运行与配置说明

当前项目只保留两个运行入口：

- `scripts/chat_agent.py`
- `scripts/openai_adapter.py`

两者启动时都会读取 `config.json` 中当前选中的 LLM 配置。

## LLM 配置方式

LLM 相关配置统一放在 `config.json` 的 `llm` 下：

```json
{
  "llm": {
    "current": "deepseek",
    "providers": {
      "deepseek": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key": "",
        "base_url": "",
        "timeout": 120
      },
      "openai": {
        "provider": "openai",
        "model": "gpt-4.1",
        "api_key": "",
        "base_url": "",
        "timeout": 120
      }
    }
  }
}
```

字段说明：

- `llm.current`: 当前正在使用的 LLM 名称
- `llm.providers.<name>.provider`: 后端标识，可自由命名，例如 `deepseek`、`openai`、`qwen`、`glm`
- `llm.providers.<name>.model`: 实际请求时使用的模型名
- `llm.providers.<name>.api_key`: 对应模型平台的 key
- `llm.providers.<name>.base_url`: 必填；可写 OpenAI SDK 风格前缀地址，也可写完整请求地址
- `llm.providers.<name>.timeout`: 请求超时秒数

说明：

- 不再提供任何内置默认 `base_url`
- 每个 provider 都必须在 `config.json` 中显式填写 `base_url`
- 如果填写的是 SDK 风格前缀，例如 `https://dashscope.aliyuncs.com/compatible-mode/v1`，代码会自动补成 `/chat/completions`
- 如果填写的已经是完整地址，例如 `https://api.deepseek.com/chat/completions`，则会直接使用

## LLM 管理脚本

新增脚本：

- `python3 scripts/llm_provider.py which`
- `python3 scripts/llm_provider.py ls`
- `python3 scripts/llm_provider.py checkout <name>`

示例：

```bash
python3 scripts/llm_provider.py which
python3 scripts/llm_provider.py ls
python3 scripts/llm_provider.py checkout deepseek
python3 scripts/llm_provider.py checkout openai
```

说明：

- `which` 会打印当前正在使用的 LLM 及其关键配置
- `ls` 会列出 `config.json` 中所有可用 LLM，并标出当前项
- `checkout` 会直接修改 `config.json` 中的 `llm.current`

## 配置优先级

统一优先级如下：

1. `config.json` 中的当前 LLM 配置
2. 代码内置默认值

说明：

- LLM 的 `provider`、`model`、`api_key`、`base_url`、`timeout` 不再依赖命令行参数和环境变量切换
- 其它非 LLM 配置仍支持环境变量覆盖，例如 `web.port`、`agent.max_steps`

## 仍支持环境变量覆盖的配置

- `HM_AGENT_MAX_STEPS` -> `agent.max_steps`
- `HM_AGENT_ROOT` -> `agent.root`
- `HM_AGENT_SESSION_STORAGE_PATH` -> `agent.session_storage_path`
- `HM_AGENT_CHAT_STORAGE_PATH` -> `agent.chat_storage_path`
- `HM_AGENT_RUN_COMMAND_TIMEOUT` -> `tools.run_command.timeout`
- `HM_AGENT_SEARCH_TEXT_MAX_RESULTS` -> `tools.search_text.max_results`
- `HM_AGENT_READ_FILE_MAX_CHARS` -> `tools.read_file.max_chars`
- `HM_AGENT_WEB_HOST` -> `web.host`
- `HM_AGENT_WEB_PORT` -> `web.port`
- `HM_AGENT_WEB_DEBUG` -> `web.debug`
- `HM_AGENT_WEB_MAX_STEPS` -> `web.max_steps`
- `HM_AGENT_CHAT_MAX_STEPS` -> `scripts.chat_agent.default_max_steps`

## 最小运行方式

### 1. 查看当前 LLM

```bash
python3 scripts/llm_provider.py which
```

### 2. 如有需要，切换当前 LLM

```bash
python3 scripts/llm_provider.py checkout openai
```

### 3. 启动交互式 CLI

```bash
python3 scripts/chat_agent.py "先分析当前工程结构"
```

可选参数：

```bash
python3 scripts/chat_agent.py "先分析当前工程结构" \
  --max-steps 120 \
  --root .
```

### 4. 启动 Web 适配层

```bash
python3 scripts/openai_adapter.py
```

常用环境变量示例：

```bash
export HM_AGENT_WEB_HOST="127.0.0.1"
export HM_AGENT_WEB_PORT="5001"
export HM_AGENT_WEB_DEBUG="false"
export HM_AGENT_WEB_MAX_STEPS="12"
```

## 何时生效

- 新启动的 `chat_agent.py` 一定会使用 `config.json` 中当前选中的 LLM
- 新启动的 `openai_adapter.py` 一定会使用 `config.json` 中当前选中的 LLM
- 已经运行中的会话不会被强行切换
- 如果切换了 `llm.current`，建议新开会话；如果是长期运行的 adapter，切换后重启进程最稳妥

## 权限相关命令

CLI / Web 都支持：

```text
/permissions
/approve /path/to/allow
```

说明：

- 当 agent 首次尝试执行工作区外写入命令时，CLI 会直接询问是否永久授权
- 同意后，授权路径会写入工作区下的 `.hm_agent_permissions.json`
- Web 请求无法在同一 HTTP 请求中弹出交互式确认，可通过 `/approve <path>` 预授权

## 常见问题

### 缺少 API Key

会直接报错，例如：

```text
未检测到 LLM API Key
```

解决方式：

- 打开 `config.json`
- 给当前使用的 `llm.providers.<current>.api_key` 填入有效值

### 启动报缺少 `base_url`

这是预期行为。现在所有 provider 都没有默认地址，必须在 `config.json` 中显式填写：

```json
{
  "provider": "openai_compatible",
  "model": "your-model-name",
  "api_key": "your-key",
  "base_url": "https://your-endpoint/v1/chat/completions",
  "timeout": 120
}
```

### 配置文件非法

如果 `config.json` 不是合法 JSON，启动时会直接报错并指出配置文件路径。

### 环境变量类型错误

例如：

- `HM_AGENT_WEB_PORT=abc`
- `HM_AGENT_WEB_DEBUG=maybe`

这类值会直接触发明确错误，而不是静默退回默认值。
