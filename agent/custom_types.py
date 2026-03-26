from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from .events import AgentEvent


@dataclass
class Message:
    role: str
    content: str


@dataclass
class ChatRequest:
    messages: List[Message]
    model: str = "deepseek-chat"
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra_body: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    model: str
    content: str
    raw: Dict[str, Any]
    usage: Dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[str] = None


StopReason = Literal["final", "max_steps", "error"]


@dataclass
class RunResult:
    final_answer: str
    stop_reason: StopReason
    step_count: int
    events: List["AgentEvent"] = field(default_factory=list)
    chat_id: str = ""
    session_id: str = ""
    error_message: str = ""
