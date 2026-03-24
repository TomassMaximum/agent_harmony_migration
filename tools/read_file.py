import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from .base import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "读取文本文件内容。参数: path, max_chars(可选，默认12000)"

    def __init__(self):
        self.default_max_chars = config.get("tools.read_file.max_chars", 12000)

    def run(self, **kwargs) -> ToolResult:
        path = kwargs.get("path")
        max_chars = kwargs.get("max_chars", self.default_max_chars)

        if not isinstance(path, str) or not path.strip():
            return ToolResult(ok=False, content="参数 path 无效")

        if not isinstance(max_chars, int) or max_chars <= 0:
            max_chars = self.default_max_chars

        try:
            if not os.path.isfile(path):
                return ToolResult(ok=False, content=f"文件不存在: {path}")

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars + 1)

            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars]

            return ToolResult(
                ok=True,
                content=content,
                meta={
                    "path": os.path.abspath(path),
                    "max_chars": max_chars,
                    "truncated": truncated,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, content=f"读取文件失败: {e}")
