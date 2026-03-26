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


StopReason = Literal[
    "final",
    "max_steps",
    "permission_blocked",
    "tool_error",
    "llm_error",
    "invalid_model_output",
    "error",
]


@dataclass
class RunResult:
    final_answer: str
    stop_reason: StopReason
    step_count: int
    events: List["AgentEvent"] = field(default_factory=list)
    chat_id: str = ""
    session_id: str = ""
    error_message: str = ""

    def user_facing_text(self) -> str:
        if self.stop_reason == "final" and self.final_answer:
            return self.final_answer
        if self.stop_reason == "max_steps":
            return "本轮执行尚未生成最终答复，已达到最大步数。"
        if self.stop_reason == "permission_blocked":
            return self.error_message or "本轮执行因权限限制而停止。"
        if self.stop_reason == "tool_error":
            return self.error_message or "本轮执行因工具异常而停止。"
        if self.stop_reason == "llm_error":
            return self.error_message or "本轮执行因模型请求失败而停止。"
        if self.stop_reason == "invalid_model_output":
            return self.error_message or "本轮执行因模型输出不符合协议而停止。"
        return self.error_message or "本轮执行失败。"
