# hm_agent

`hm_agent` 当前是一个面向工程探索与迁移辅助的 agent 底座，已经完成里程碑 1 的收口工作。

当前状态：

- 已有统一执行主干
- 已有统一事件协议、停止原因与 trace 输出
- 已有 chat / session 记忆
- 已有最小权限阻断
- 已有基线测试
- 当前只保留两个正式入口：
  - `scripts/chat_agent.py`
  - `scripts/openai_adapter.py`

项目还没有进入文档中定义的完整迁移闭环。当前更准确的定位是：

- “稳定的 agent 底座”
- 不是“完整的分阶段迁移 orchestrator”

## 当前支持能力

- 交互式 CLI 调试
- OpenAI 风格 Web 适配层
- 工具调用与事件追踪
- chat / session 持久化
- 分类停止原因：
  - `final`
  - `max_steps`
  - `permission_blocked`
  - `tool_error`
  - `llm_error`
  - `invalid_model_output`

## 当前限制

- 还没有 `project_memory/` 和结构化工程产物
- 还没有 `Analyze -> Design -> Implement -> Review` 的阶段编排
- 权限策略目前是最小可控版本：
  - 只读命令默认允许
  - `run_command` 的工作区外路径修改会先申请授权
  - CLI 中用户同意后会永久写入授权配置
  - Web 中可通过 `/approve <path>` 做永久授权

## 快速开始

### 1. 配置 API Key

```bash
export DEEPSEEK_API_KEY="你的 key"
```

### 2. 启动交互式 CLI

```bash
python3 scripts/chat_agent.py "先分析当前工程结构"
```

权限相关命令：

```bash
/permissions
/approve /path/to/allow
```

### 3. 启动 Web 适配层

```bash
python3 scripts/openai_adapter.py
```

如果 Web 请求被权限阻塞，可发送：

```text
/approve /path/to/allow
```

## 文档

- 开发路线图：[docs/development_roadmap.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/development_roadmap.md)
- 运行与配置：[docs/runtime_config.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/runtime_config.md)
- 基线测试：[docs/testing_baseline.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/testing_baseline.md)
- MVP 目标：[docs/MVP_minimum.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/MVP_minimum.md)
- 记忆模块说明：[docs/memory_module.md](/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/memory_module.md)

## 基线测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

当前基线测试不依赖真实 API key。

## 下一步

下一阶段重点是里程碑 2：

- 引入 `project_memory/`
- 落地 `project_overview.json`
- 为 Analyze 阶段提供结构化产物输出
