import os
from typing import List

from .base import BaseTool, ToolResult


class ListDirTool(BaseTool):
    name = "list_dir"
    description = "列出指定目录下的文件和文件夹。参数: path"

    def run(self, **kwargs) -> ToolResult:
        path = kwargs.get("path", ".")
        if not isinstance(path, str) or not path.strip():
            return ToolResult(ok=False, content="参数 path 无效")

        try:
            entries = os.listdir(path)
            entries.sort()

            lines: List[str] = []
            for name in entries:
                full_path = os.path.join(path, name)
                if os.path.isdir(full_path):
                    lines.append(f"[DIR]  {name}")
                else:
                    lines.append(f"[FILE] {name}")

            return ToolResult(
                ok=True,
                content="\n".join(lines) if lines else "(empty directory)",
                meta={"path": os.path.abspath(path), "count": len(entries)},
            )
        except Exception as e:
            return ToolResult(ok=False, content=f"列目录失败: {e}")