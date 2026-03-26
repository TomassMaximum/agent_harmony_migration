from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional
import time
import uuid

EventType = Literal[
    "thought",
    "tool_call",
    "tool_result",
    "final",
    "error",
]

TraceEntryKind = Literal["thought", "tool", "result", "final", "error"]

# User-visible trace only includes high-level reasoning and outcomes.
# Raw tool arguments, rendered commands, status flags and timestamps stay in the
# original AgentEvent for debugging and internal inspection.
USER_TRACE_FIELDS_BY_TYPE: Dict[EventType, tuple[str, ...]] = {
    "thought": ("content",),
    "tool_call": ("tool_name",),
    "tool_result": ("result",),
    "final": ("content",),
    "error": ("content",),
}


@dataclass
class AgentEvent:
    type: EventType
    step: int

    content: Optional[str] = None

    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    command: Optional[str] = None

    result: Optional[Any] = None
    status: Optional[str] = None

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TraceEntry:
    step: int
    kind: TraceEntryKind
    text: str


@dataclass
class TraceStepView:
    step: int
    thought: str = ""
    tool_name: str = ""
    result_summary: str = ""
    final_answer: str = ""
    error: str = ""

    def has_visible_content(self) -> bool:
        return any([
            self.thought,
            self.tool_name,
            self.result_summary,
            self.final_answer,
            self.error,
        ])


def summarize_tool_result(result: Any, limit: int = 240) -> str:
    if not isinstance(result, dict):
        text = str(result or "").strip()
        return text if len(text) <= limit else text[:limit] + "..."

    content = result.get("content", "")
    if not isinstance(content, str):
        content = str(content)
    content = content.replace("\n", " ").strip()
    return content if len(content) <= limit else content[:limit] + "..."


def iter_user_trace_entries(events: List[AgentEvent]) -> List[TraceEntry]:
    trace_entries: List[TraceEntry] = []

    for event in events:
        step = int(getattr(event, "step", 0) or 0)
        if step <= 0:
            step = 1

        if event.type == "thought" and event.content:
            trace_entries.append(
                TraceEntry(step=step, kind="thought", text=event.content.strip())
            )
            continue

        if event.type == "tool_call":
            tool_name = (event.tool_name or "").strip()
            if tool_name:
                trace_entries.append(
                    TraceEntry(step=step, kind="tool", text=tool_name)
                )
            continue

        if event.type == "tool_result":
            summary = summarize_tool_result(event.result)
            if summary:
                trace_entries.append(
                    TraceEntry(step=step, kind="result", text=summary)
                )
            continue

        if event.type == "final" and event.content:
            trace_entries.append(
                TraceEntry(step=step, kind="final", text=event.content.strip())
            )
            continue

        if event.type == "error" and event.content:
            trace_entries.append(
                TraceEntry(step=step, kind="error", text=event.content.strip())
            )

    return trace_entries


def build_trace_steps(events: List[AgentEvent]) -> List[TraceStepView]:
    grouped: List[TraceStepView] = []
    step_map: Dict[int, TraceStepView] = {}

    for entry in iter_user_trace_entries(events):
        if entry.step not in step_map:
            step_map[entry.step] = TraceStepView(step=entry.step)
            grouped.append(step_map[entry.step])

        item = step_map[entry.step]

        if entry.kind == "thought":
            item.thought = entry.text
            continue
        if entry.kind == "tool":
            item.tool_name = entry.text
            continue
        if entry.kind == "result":
            item.result_summary = entry.text
            continue
        if entry.kind == "final":
            item.final_answer = entry.text
            continue
        if entry.kind == "error":
            item.error = entry.text

    return grouped


def trace_entry_to_text(entry: TraceEntry) -> str:
    if entry.kind == "final":
        return entry.text
    return f"{entry.kind}: {entry.text}"


def validate_event_shape(event: AgentEvent) -> bool:
    required_fields = USER_TRACE_FIELDS_BY_TYPE.get(event.type, ())
    for field_name in required_fields:
        value = getattr(event, field_name, None)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
    return True


def trace_step_to_payload(step: TraceStepView) -> Dict[str, Any]:
    return {
        "step": step.step,
        "thought": step.thought,
        "tool": step.tool_name,
        "result": step.result_summary,
        "final": step.final_answer,
        "error": step.error,
    }


def trace_steps_to_payload(steps: List[TraceStepView]) -> List[Dict[str, Any]]:
    return [trace_step_to_payload(step) for step in steps if step.has_visible_content()]


def event_debug_payload(event: AgentEvent) -> Dict[str, Any]:
    return {
        "type": event.type,
        "step": event.step,
        "content": event.content,
        "tool_name": event.tool_name,
        "tool_args": event.tool_args,
        "command": event.command,
        "result": event.result,
        "status": event.status,
        "event_id": event.event_id,
        "timestamp": event.timestamp,
    }
