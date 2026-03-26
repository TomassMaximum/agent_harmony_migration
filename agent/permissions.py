import json
import os
import shlex
from dataclasses import dataclass, field
from typing import List, Optional, Set


PATH_MUTATING_COMMANDS = {
    "rm",
    "mv",
    "cp",
    "ln",
    "mkdir",
    "rmdir",
    "touch",
    "truncate",
    "tee",
    "chmod",
    "chown",
}


@dataclass
class PermissionDecision:
    allowed: bool
    reason: str
    requires_user_approval: bool = False
    requested_paths: List[str] = field(default_factory=list)


class PermissionManager:
    def __init__(self, workspace_root: str, store_path: Optional[str] = None) -> None:
        self.workspace_root = os.path.abspath(os.path.expanduser(workspace_root))
        self.store_path = store_path or os.path.join(self.workspace_root, ".hm_agent_permissions.json")
        self.allowed_write_roots: Set[str] = set()
        self._load()

    def is_within_workspace(self, path: str) -> bool:
        abs_path = os.path.abspath(os.path.expanduser(path))
        return (
            abs_path == self.workspace_root
            or abs_path.startswith(self.workspace_root + os.sep)
        )

    def is_within_allowed_write_roots(self, path: str) -> bool:
        abs_path = os.path.abspath(os.path.expanduser(path))
        for root in self.allowed_write_roots:
            if abs_path == root or abs_path.startswith(root + os.sep):
                return True
        return False

    def grant_write_access(self, path: str) -> None:
        abs_path = os.path.abspath(os.path.expanduser(path))

        if os.path.isdir(abs_path):
            grant_root = abs_path
        else:
            grant_root = os.path.dirname(abs_path)

        self.allowed_write_roots.add(grant_root)
        self._save()

    def describe_allowed_write_roots(self) -> str:
        if not self.allowed_write_roots:
            return "(none)"
        return "\n".join(sorted(self.allowed_write_roots))

    def check_run_command(self, command: str, cwd: Optional[str]) -> PermissionDecision:
        stripped = (command or "").strip()
        if not stripped:
            return PermissionDecision(
                allowed=False,
                reason="empty command",
                requires_user_approval=False,
            )

        try:
            tokens = shlex.split(stripped)
        except Exception:
            # 解析不了的命令，按你的要求：默认放行
            return PermissionDecision(
                allowed=True,
                reason="command parse failed, but policy allows it",
            )

        if not tokens:
            return PermissionDecision(
                allowed=False,
                reason="empty parsed command",
                requires_user_approval=False,
            )

        base_cmd = tokens[0].lower()

        # 不是显式路径修改命令，全部放行
        if base_cmd not in PATH_MUTATING_COMMANDS:
            return PermissionDecision(
                allowed=True,
                reason="non path-mutating command is allowed by policy",
            )

        target_paths = self._extract_target_paths(tokens)
        if not target_paths:
            # 没有明确路径目标，也按你的要求放行
            return PermissionDecision(
                allowed=True,
                reason="no explicit target path found, allowed by policy",
            )

        resolved_paths: List[str] = []
        for p in target_paths:
            resolved_paths.append(self._resolve_path(p, cwd))

        blocked_paths: List[str] = []
        for p in resolved_paths:
            if self.is_within_workspace(p):
                continue
            if self.is_within_allowed_write_roots(p):
                continue
            blocked_paths.append(p)

        if blocked_paths:
            return PermissionDecision(
                allowed=False,
                reason="path-mutating command targets path outside workspace",
                requires_user_approval=True,
                requested_paths=blocked_paths,
            )

        return PermissionDecision(
            allowed=True,
            reason="mutating targets are inside workspace or already approved",
        )

    def _resolve_path(self, path_str: str, cwd: Optional[str]) -> str:
        expanded = os.path.expanduser(path_str)

        if os.path.isabs(expanded):
            return os.path.abspath(expanded)

        base_dir = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
        return os.path.abspath(os.path.join(base_dir, expanded))

    def _extract_target_paths(self, tokens: List[str]) -> List[str]:
        if not tokens:
            return []

        cmd = tokens[0].lower()
        args = tokens[1:]

        path_like_args: List[str] = []
        for a in args:
            if a.startswith("-"):
                continue
            if self._looks_like_path(a):
                path_like_args.append(a)

        if cmd in {"touch", "mkdir", "rmdir", "rm", "chmod", "chown", "truncate", "tee"}:
            return path_like_args

        if cmd in {"mv", "cp", "ln"}:
            return path_like_args[-2:] if len(path_like_args) >= 2 else path_like_args

        return path_like_args

    def _looks_like_path(self, value: str) -> bool:
        if not value:
            return False
        if value in {".", ".."}:
            return True
        if value.startswith(("~/", "/", "./", "../")):
            return True
        if "/" in value:
            return True
        if "." in value:
            return True
        return True

    def _load(self) -> None:
        if not os.path.isfile(self.store_path):
            return

        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            roots = data.get("allowed_write_roots", [])
            if isinstance(roots, list):
                self.allowed_write_roots = {
                    os.path.abspath(os.path.expanduser(p))
                    for p in roots
                    if isinstance(p, str) and p.strip()
                }
        except Exception:
            self.allowed_write_roots = set()

    def _save(self) -> None:
        data = {
            "allowed_write_roots": sorted(self.allowed_write_roots)
        }

        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
