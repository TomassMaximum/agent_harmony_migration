# 基线测试说明

当前项目的基线测试使用 Python 标准库 `unittest`，不依赖真实 API key，也不依赖额外测试框架。

## 执行命令

在项目根目录执行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

如果只想先做语法校验，可以执行：

```bash
python3 -m py_compile scripts/*.py agent/*.py tools/*.py config.py tests/*.py
```

## 当前覆盖范围

### `tests/test_memory.py`

覆盖：

- `agent/memory.py`
- `agent/chat_memory.py`

验证点：

- session 原始消息保存与读取
- session 摘要保存与排序
- chat 创建与 session 关联
- 非法 chat meta 文件不会阻断列表读取

### `tests/test_tools.py`

覆盖：

- `tools/read_file.py`
- `tools/search_text.py`
- `tools/run_command.py`

验证点：

- `read_file` 截断与 `meta.truncated`
- `search_text` 搜索结果与 `meta.count`
- `run_command` 输出结构与 `exit_code`

### `tests/test_loop.py`

覆盖：

- `agent/loop.py`

验证点：

- `final`
- `max_steps`
- `permission_blocked`
- `llm_error`
- `invalid_model_output`
- `tool_error`

说明：

- 这里通过 mock `create_llm()` 和局部替换 `step_once()` / `tool.run()`，避免真实网络调用

### `tests/test_llm.py`

覆盖：

- `agent/llm.py`

验证点：

- provider alias 归一化
- provider 缺少 `base_url` 的报错
- `openai_compatible` 缺少 `base_url` 的报错

### `tests/test_config.py`

覆盖：

- `config.py`

验证点：

- `llm.current` 切换后会写回 `config.json`
- 旧版单一 `llm` 配置可自动迁移为新的 `llm.providers` 结构

### `tests/test_openai_adapter.py`

覆盖：

- `scripts/openai_adapter.py` 的关键纯函数
- `scripts/entry_common.py` 的 Web trace 组合逻辑

验证点：

- 用户输入归一化
- OpenWebUI meta request 识别
- conversation key 派生稳定性
- Web trace markdown 拼接

### `tests/test_project_memory.py`

覆盖：

- `agent/project_memory.py`

验证点：

- 默认 `project_memory` 路径落在目标鸿蒙工程下
- 显式路径优先级
- 最小目录结构初始化
- `builder_job`、`project_overview` 等基础 schema 校验

### `tests/test_phase1_module_analysis.py`

覆盖：

- `agent/phase1_module_analysis.py`

验证点：

- 模块层分析默认输出到目标工程 `.migration/project_memory/`
- 本地 review 能发现高信号包未覆盖
- LLM 输出重试后可持久化模块层产物

### `tests/test_page_analysis.py`

覆盖：

- `agent/page_analysis.py`

验证点：

- 页面层组件识别与 module 归属
- manifest activity 覆盖校验
- module package binding 补全
- 页面层分析重试与持久化

### `tests/test_unknown_queue.py`

覆盖：

- `agent/unknown_queue.py`
- `scripts/review_unknown_queue.py` 依赖的纯函数路径

验证点：

- 待确认项筛选与 page mapping 聚合
- unknown 确认后写入 decisions 并更新 queue
- unknown 延后处理
- 确认阈值写回 `builder_job.json`

## 运行预期

当前基线测试通过时，典型输出应为：

```text
Ran 51 tests in ...

OK
```

测试过程中，`derive_fallback_conversation_key()` 会向 stderr 打少量调试信息，不影响测试结果。

## 建议使用方式

每次改动以下模块后，至少跑一遍基线测试：

- `agent/loop.py`
- `agent/events.py`
- `agent/custom_types.py`
- `scripts/chat_agent.py`
- `scripts/openai_adapter.py`
- `tools/`
- `agent/memory.py`
- `agent/chat_memory.py`
- `agent/project_memory.py`
- `agent/phase1_module_analysis.py`
- `agent/page_analysis.py`
- `agent/unknown_queue.py`
