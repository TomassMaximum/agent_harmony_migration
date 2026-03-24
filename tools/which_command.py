import shutil

from .base import BaseTool, ToolResult


class WhichCommandTool(BaseTool):
    name = "which_command"
    description = "查找命令对应的可执行文件路径。参数: command_name"

    def run(self, **kwargs) -> ToolResult:
        command_name = kwargs.get("command_name")
        if not isinstance(command_name, str) or not command_name.strip():
            return ToolResult(ok=False, content="参数 command_name 无效")

        path = shutil.which(command_name.strip())
        if path:
            return ToolResult(ok=True, content=path)
        return ToolResult(ok=False, content=f"未找到命令: {command_name}")