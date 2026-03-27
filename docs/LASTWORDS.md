# OHOS Lastwords

## Task

开始里程碑 2，落地结构化工程记忆，先实现 `project_memory/` 和 `project_overview.json`。

## Done

- 里程碑 1 已完成：执行主干、两类入口、事件协议、停止原因、权限策略、配置和基线测试都已收口。
- 当前正式入口只剩 `scripts/chat_agent.py` 和 `scripts/openai_adapter.py`。
- 提示词入口已统一到 `agent/prompts.py`。
- 权限授权已改为“拒绝后申请，授权后永久写入 `.hm_agent_permissions.json`”。
- 基线测试已就位，并通过 `python3 -m unittest discover -s tests -p 'test_*.py' -v`。

## Pending

- 新建 `project_memory/` 目录结构与最小 schema。
- 先定义 `project_overview.json` 的字段：工程根、关键模块、语言/框架、入口文件、迁移范围、风险点、更新时间。
- 明确结构化产物和现有 `chat/session` 记忆的关系：
  - `chat/session` 继续服务对话连续性
  - `project_memory` 负责工程状态恢复
- 在 `AgentLoop` 外或其上层增加工程状态读写入口，不要把 `project_overview.json` 继续塞回纯聊天消息。
- 为 Analyze 阶段接入最小产物输出链路。

## Blockers

- None

## Next Step

下一会话先不要写 orchestrator。先在 `docs/` 或 `agent/` 内把 `project_overview.json` 的最小 schema 定下来，再落一个最小持久化实现，优先保证“能生成、能读取、能恢复”。

## Changed Files

- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/agent/loop.py`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/agent/events.py`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/agent/custom_types.py`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/agent/permissions.py`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/agent/prompts.py`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/scripts/chat_agent.py`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/scripts/openai_adapter.py`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/scripts/entry_common.py`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/development_roadmap.md`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/runtime_config.md`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/docs/testing_baseline.md`
- `/Users/weibaoping/agent/ohos_migration/ohmv1/hm_agent/README.md`

## Build Status

- 已执行：
  - `python3 -m unittest discover -s tests -p 'test_*.py' -v`
  - `python3 -m py_compile scripts/*.py agent/*.py tools/*.py config.py tests/*.py`
- 当前结果：Passed
