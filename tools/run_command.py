import subprocess
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from .base import BaseTool, ToolResult


class RunCommandTool(BaseTool):
    name = "run_command"
    description = "执行 shell 命令。参数: command, cwd(可选), timeout(可选，默认60秒)"

    def __init__(self):
        self.default_timeout = config.get("tools.run_command.timeout", 60)

    def run(self, **kwargs) -> ToolResult:
        command = kwargs.get("command")
        cwd = kwargs.get("cwd", None)
        timeout = kwargs.get("timeout", self.default_timeout)

        if not isinstance(command, str) or not command.strip():
            return ToolResult(ok=False, content="参数 command 无效")

        if not isinstance(timeout, int) or timeout <= 0:
            timeout = self.default_timeout

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )

            output = (
                f"[exit_code] {completed.returncode}\n"
                f"\n[stdout]\n{completed.stdout}\n"
                f"\n[stderr]\n{completed.stderr}"
            )

            return ToolResult(
                ok=(completed.returncode == 0),
                content=output,
                meta={
                    "exit_code": completed.returncode,
                    "cwd": cwd,
                    "timeout": timeout,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, content=f"命令执行超时（>{timeout}s）")
        except Exception as e:
            return ToolResult(ok=False, content=f"执行命令失败: {e}")
