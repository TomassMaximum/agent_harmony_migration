from dataclasses import dataclass, field
from typing import Any, Optional, Literal
import time
import uuid

EventType = Literal[
    "thought",
    "tool_call",
    "tool_result",
    "final",
    "error",
]

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