from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    ok: bool
    content: str
    meta: Optional[Dict[str, Any]] = None


class BaseTool:
    name: str = ""
    description: str = ""

    def run(self, **kwargs) -> ToolResult:
        raise NotImplementedError
