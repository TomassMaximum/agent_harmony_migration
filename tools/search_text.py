import os
from typing import List

from .base import BaseTool, ToolResult


class SearchTextTool(BaseTool):
    name = "search_text"
    description = (
        "在目录中递归搜索文本。参数: root, keyword, "
        "file_extensions(可选，如 ['.py', '.ts', '.ets']), max_results(可选)"
    )

    def run(self, **kwargs) -> ToolResult:
        root = kwargs.get("root", ".")
        keyword = kwargs.get("keyword")
        file_extensions = kwargs.get("file_extensions")
        max_results = kwargs.get("max_results", 30)

        if not isinstance(keyword, str) or not keyword.strip():
            return ToolResult(ok=False, content="参数 keyword 无效")

        if not isinstance(max_results, int) or max_results <= 0:
            max_results = 30

        ext_filter = None
        if isinstance(file_extensions, list):
            ext_filter = set(str(x) for x in file_extensions)

        results: List[str] = []

        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames
                    if d not in {
                        ".git", ".idea", ".gradle", "build", "dist", "node_modules",
                        "oh_modules", ".hvigor", ".next", "__pycache__"
                    }
                ]

                for filename in filenames:
                    if ext_filter:
                        _, ext = os.path.splitext(filename)
                        if ext not in ext_filter:
                            continue

                    file_path = os.path.join(dirpath, filename)

                    try:
                        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                            for idx, line in enumerate(f, start=1):
                                if keyword in line:
                                    results.append(f"{file_path}:{idx}: {line.rstrip()}")
                                    if len(results) >= max_results:
                                        return ToolResult(
                                            ok=True,
                                            content="\n".join(results),
                                            meta={"count": len(results), "truncated": True},
                                        )
                    except Exception:
                        continue

            return ToolResult(
                ok=True,
                content="\n".join(results) if results else "(no matches)",
                meta={"count": len(results), "truncated": False},
            )

        except Exception as e:
            return ToolResult(ok=False, content=f"搜索失败: {e}")