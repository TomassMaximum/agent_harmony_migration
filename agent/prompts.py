from typing import Any, Dict, List


AGENT_SYSTEM_PROMPT = """你是一个正在搭建自己的工程迁移助手。

你的工作是检查代码库，逐步推理，并决定下一步使用哪个工具，升级哪一部分功能。

你必须只输出合法的 JSON。

响应格式：
{
  "thought": "简短推理",
  "action": "tool" 或 "final",
  "tool_name": "可用工具之一，或空字符串（如果是 final）",
  "tool_args": { ... },
  "final_answer": "仅当 action 为 final 时填写"
}

规则：
1. 只输出 JSON，不要用 markdown 代码块。
2. 优先采用小而专注的步骤。
3. 只读取需要的文件。
4. 如果需要更多信息，选择工具。
5. 如果已有足够信息，设置 action 为 final。
6. 优先使用只读工具：list_dir、read_file、search_text、which_command、get_env_var。
7. 仅在必要时使用 run_command。
8. 除非用户明确要求，避免使用修改性命令。
9. 保持 thought 简洁。
"""

WEB_CHAT_INIT_TASK = (
    "你现在处于 Web 聊天模式。"
    "直接响应用户当前消息，不要默认探索工程，不要主动执行工具。"
    "只有在用户明确提出需要查看文件、目录、执行命令或分析工程时，才使用工具。"
)

SESSION_SUMMARY_SYSTEM_PROMPT = "你是一个负责压缩工程 session 记忆的助手。"
CHAT_SUMMARY_SYSTEM_PROMPT = "你是一个负责维护 chat 长期记忆摘要的助手。"


def build_current_chat_memory_block(chat_id: str, meta: Dict[str, Any], session_summaries: List[Dict[str, Any]]) -> str:
    if not meta:
        return ""

    if not meta.get("summary") and not session_summaries:
        return ""

    lines: List[str] = []
    lines.append("以下是当前恢复的历史 chat 记忆。")
    lines.append(f"Current chat id: {chat_id}")
    lines.append(f"Chat title: {meta.get('title', '')}")
    lines.append(f"Chat summary: {meta.get('summary', '')}")
    lines.append("")
    lines.append("该 chat 下的 session 摘要列表：")

    for idx, item in enumerate(session_summaries, start=1):
        lines.append(
            f"{idx}. session_id={item.get('session_id', '')}\n"
            f"   title={item.get('title', '')}\n"
            f"   summary={item.get('summary', '')}"
        )

    lines.append("")
    lines.append(
        "如果你需要某个历史 session 的细节，可以使用：\n"
        "- list_chat_session_summaries(chat_id)\n"
        "- read_session_messages(session_id)\n"
        "来按需查看历史原始消息。"
    )
    return "\n".join(lines)


def build_session_start_message(
    root: str,
    chat_id: str,
    session_id: str,
    tools_text: str,
    task: str,
) -> str:
    return (
        f"Workspace root:\n{root}\n\n"
        f"Current chat id:\n{chat_id}\n\n"
        f"Current session id:\n{session_id}\n\n"
        f"Available tools:\n{tools_text}\n\n"
        f"Initial task:\n{task}\n\n"
        "Please explore step by step and help the user complete the task."
    )


def build_tool_feedback_message(tool_feedback: str) -> str:
    return (
        "Tool execution result:\n"
        f"{tool_feedback}\n\n"
        "Interpretation rules:\n"
        "1. If ok is true, the tool executed successfully.\n"
        "2. Only treat permission as blocked when meta.blocked_by_permission is true,\n"
        "   or the content explicitly says the user did not grant permission.\n"
        "3. Do NOT infer permission problems merely because filenames, paths, or text\n"
        "   contain words like 'permission', 'permissions', '权限', or similar.\n"
        "4. If ok is true, continue the task based on the actual tool result.\n\n"
        "Based on this result, decide the next action."
    )


def build_session_summary_prompt(raw_text: str) -> str:
    return (
        "请把下面这个 session 的对话压缩成结构化摘要。\n\n"
        "输出 JSON：\n"
        "{\n"
        '  "title": "...",\n'
        '  "summary": "...",\n'
        '  "key_points": ["...", "..."]\n'
        "}\n\n"
        "要求：\n"
        "1. 重点保留已完成的工作、关键决策、当前状态、未完成事项。\n"
        "2. 删除寒暄和重复内容。\n"
        "3. title 要具体。\n\n"
        f"原始内容如下：\n{raw_text}"
    )


def build_chat_summary_prompt(chat_meta: Dict[str, Any], session_summaries: List[Dict[str, Any]]) -> str:
    summary_blocks: List[str] = []
    for idx, item in enumerate(session_summaries, start=1):
        summary_blocks.append(
            f"{idx}. session_id={item.get('session_id', '')}\n"
            f"title={item.get('title', '')}\n"
            f"summary={item.get('summary', '')}"
        )

    return (
        "请根据以下多个 session 摘要，更新这个 chat 的整体标题和摘要。\n\n"
        "输出 JSON：\n"
        "{\n"
        '  "title": "...",\n'
        '  "summary": "..."\n'
        "}\n\n"
        "要求：\n"
        "1. title 概括整个 chat 的长期主题。\n"
        "2. summary 概括整体进展，而不是单次 session。\n"
        "3. 如果已有标题/摘要合理，请延续其方向更新。\n\n"
        f"已有 chat 标题：{chat_meta.get('title', '')}\n"
        f"已有 chat 摘要：{chat_meta.get('summary', '')}\n\n"
        "各 session 摘要如下：\n"
        + "\n\n".join(summary_blocks)
    )
