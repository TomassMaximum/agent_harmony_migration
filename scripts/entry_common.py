#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import List, Optional

from agent.events import (
    AgentEvent,
    TraceStepView,
    build_trace_steps,
    iter_user_trace_entries,
    trace_steps_to_payload,
    trace_entry_to_text,
)
from agent.loop import AgentLoop


def build_agent(
    model: Optional[str] = None,
    max_steps: Optional[int] = None,
    root: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> AgentLoop:
    return AgentLoop(
        model=model,
        max_steps=max_steps,
        root=root,
        chat_id=chat_id,
    )


def start_new_session(
    agent: AgentLoop,
    task: str,
    inject_current_chat_memory: bool = True,
) -> None:
    agent.start_session(
        task,
        load_existing=False,
        inject_current_chat_memory=inject_current_chat_memory,
    )


def run_entry_turn(
    agent: AgentLoop,
    max_steps: int,
    user_message: Optional[str] = None,
    on_step=None,
):
    if user_message is not None:
        agent.inject_user_message(user_message)
    return agent.run_until_stop(max_steps=max_steps, on_step=on_step)


def render_cli_step_text(events: List[AgentEvent]) -> str:
    lines = [trace_entry_to_text(entry) for entry in iter_user_trace_entries(events)]
    return "\n".join(lines).strip()


def group_events_by_step(events: List[AgentEvent]) -> List[TraceStepView]:
    return build_trace_steps(events)


def render_web_step_markdown(step_index: int, event_group: TraceStepView) -> str:
    lines = [f"[step {step_index}]"]

    thought = (event_group.thought or "").strip()
    tool_name = (event_group.tool_name or "").strip()
    result_summary = (event_group.result_summary or "").strip()
    final_answer = (event_group.final_answer or "").strip()
    error = (event_group.error or "").strip()

    if thought:
        lines.append(f"thought: {thought}")
    if tool_name:
        lines.append(f"tool: {tool_name}")
    if result_summary:
        lines.append(f"result: {result_summary}")
    if final_answer:
        lines.append(f"final: {final_answer}")
    if error:
        lines.append(f"error: {error}")

    body = "\n".join(lines)
    return f"```text\n{body}\n```\n\n"


def render_web_trace_markdown(trace_events: List[TraceStepView]) -> str:
    if not trace_events:
        return ""

    parts = ["---", "### 执行过程"]
    display_index = 0

    for event in trace_events:
        if not event.has_visible_content():
            continue

        display_index += 1
        parts.append(f"#### Step {display_index}")

        if event.thought:
            parts.append(f"- **thought**: {event.thought}")
        if event.tool_name:
            parts.append(f"- **tool**: `{event.tool_name}`")
        if event.result_summary:
            parts.append(f"- **result**: {event.result_summary}")
        if event.final_answer:
            parts.append(f"- **final**: {event.final_answer}")
        if event.error:
            parts.append(f"- **error**: {event.error}")

        parts.append("")

    return "\n".join(parts).strip()


def compose_web_response(final_text: str, trace_events: List[TraceStepView]) -> str:
    trace_md = render_web_trace_markdown(trace_events[-20:])
    final_text = (final_text or "").strip()
    if trace_md:
        return f"{final_text}\n\n{trace_md}".strip()
    return final_text


def render_web_trace_payload(trace_events: List[TraceStepView]) -> List[dict]:
    return trace_steps_to_payload(trace_events)
