from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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