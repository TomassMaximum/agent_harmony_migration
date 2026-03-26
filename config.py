import json
import os
from typing import Any, Dict, Optional

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

_config: Dict[str, Any] = {}

ENV_KEY_MAP: Dict[str, str] = {
    "agent.model": "HM_AGENT_MODEL",
    "agent.max_steps": "HM_AGENT_MAX_STEPS",
    "agent.root": "HM_AGENT_ROOT",
    "agent.session_storage_path": "HM_AGENT_SESSION_STORAGE_PATH",
    "agent.chat_storage_path": "HM_AGENT_CHAT_STORAGE_PATH",
    "llm.api_key": "DEEPSEEK_API_KEY",
    "llm.base_url": "DEEPSEEK_BASE_URL",
    "llm.timeout": "DEEPSEEK_TIMEOUT",
    "tools.run_command.timeout": "HM_AGENT_RUN_COMMAND_TIMEOUT",
    "tools.search_text.max_results": "HM_AGENT_SEARCH_TEXT_MAX_RESULTS",
    "tools.read_file.max_chars": "HM_AGENT_READ_FILE_MAX_CHARS",
    "web.host": "HM_AGENT_WEB_HOST",
    "web.port": "HM_AGENT_WEB_PORT",
    "web.debug": "HM_AGENT_WEB_DEBUG",
    "web.max_steps": "HM_AGENT_WEB_MAX_STEPS",
    "scripts.chat_agent.default_max_steps": "HM_AGENT_CHAT_MAX_STEPS",
}


def load_config() -> Dict[str, Any]:
    global _config
    if not _config:
        if not os.path.exists(CONFIG_PATH):
            # 如果配置文件不存在，返回空字典，后续使用默认值
            _config = {}
        else:
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    _config = json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"配置文件不是合法 JSON: {CONFIG_PATH}: {e}") from e
    return _config


def _get_config_value(key: str) -> Optional[Any]:
    config = load_config()
    keys = key.split(".")
    value: Any = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return None
    return value


def _parse_env_value(raw: str, fallback: Any) -> Any:
    if isinstance(fallback, bool):
        lowered = raw.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise RuntimeError(f"无效布尔配置值: {raw}")

    if isinstance(fallback, int) and not isinstance(fallback, bool):
        try:
            return int(raw.strip())
        except ValueError as e:
            raise RuntimeError(f"无效整型配置值: {raw}") from e

    if isinstance(fallback, float):
        try:
            return float(raw.strip())
        except ValueError as e:
            raise RuntimeError(f"无效浮点配置值: {raw}") from e

    return raw


def get(key: str, default: Any = None) -> Any:
    config_value = _get_config_value(key)
    fallback = config_value if config_value is not None else default

    env_name = ENV_KEY_MAP.get(key)
    if env_name:
        raw_env = os.getenv(env_name)
        if raw_env is not None:
            return _parse_env_value(raw_env, fallback)

    if config_value is not None:
        return config_value
    return default


# 预加载配置
load_config()
