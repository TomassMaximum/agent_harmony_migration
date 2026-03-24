import os

from .base import BaseTool, ToolResult


class GetEnvVarTool(BaseTool):
    name = "get_env_var"
    description = "读取环境变量。参数: name"

    def run(self, **kwargs) -> ToolResult:
        name = kwargs.get("name")
        if not isinstance(name, str) or not name.strip():
            return ToolResult(ok=False, content="参数 name 无效")

        value = os.environ.get(name)
        if value is None:
            return ToolResult(ok=False, content=f"环境变量不存在: {name}")
        return ToolResult(ok=True, content=value)