import json
import os
from copy import deepcopy
from typing import Any, Dict, Optional

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_LLM_TIMEOUT = 120
DEFAULT_CURRENT_LLM = "deepseek"
DEFAULT_LLM_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key": "",
        "base_url": "",
        "timeout": DEFAULT_LLM_TIMEOUT,
    },
    "openai": {
        "provider": "openai",
        "model": "gpt-4.1",
        "api_key": "",
        "base_url": "",
        "timeout": DEFAULT_LLM_TIMEOUT,
    },
}

_config: Dict[str, Any] = {}

ENV_KEY_MAP: Dict[str, str] = {
    "agent.max_steps": "HM_AGENT_MAX_STEPS",
    "agent.root": "HM_AGENT_ROOT",
    "agent.session_storage_path": "HM_AGENT_SESSION_STORAGE_PATH",
    "agent.chat_storage_path": "HM_AGENT_CHAT_STORAGE_PATH",
    "tools.run_command.timeout": "HM_AGENT_RUN_COMMAND_TIMEOUT",
    "tools.search_text.max_results": "HM_AGENT_SEARCH_TEXT_MAX_RESULTS",
    "tools.read_file.max_chars": "HM_AGENT_READ_FILE_MAX_CHARS",
    "web.host": "HM_AGENT_WEB_HOST",
    "web.port": "HM_AGENT_WEB_PORT",
    "web.debug": "HM_AGENT_WEB_DEBUG",
    "web.max_steps": "HM_AGENT_WEB_MAX_STEPS",
    "scripts.chat_agent.default_max_steps": "HM_AGENT_CHAT_MAX_STEPS",
}


def _deepcopy_json_like(data: Any) -> Any:
    return deepcopy(data)


def _ensure_llm_entry(name: str, raw_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    entry = dict(raw_entry or {})
    entry.setdefault("provider", name)
    entry.setdefault("model", "")
    entry.setdefault("api_key", "")
    entry.setdefault("base_url", "")
    entry.setdefault("timeout", DEFAULT_LLM_TIMEOUT)
    return entry


def _build_legacy_llm_section(config_data: Dict[str, Any]) -> Dict[str, Any]:
    llm_block = config_data.get("llm") if isinstance(config_data.get("llm"), dict) else {}
    agent_block = config_data.get("agent") if isinstance(config_data.get("agent"), dict) else {}

    current = str(llm_block.get("provider") or DEFAULT_CURRENT_LLM)
    providers = _deepcopy_json_like(DEFAULT_LLM_PROVIDERS)
    providers[current] = _ensure_llm_entry(
        current,
        {
            "provider": current,
            "model": agent_block.get("model", providers.get(current, {}).get("model", "")),
            "api_key": llm_block.get("api_key", ""),
            "base_url": llm_block.get("base_url", ""),
            "timeout": llm_block.get("timeout", DEFAULT_LLM_TIMEOUT),
        },
    )

    return {
        "current": current,
        "providers": providers,
    }


def _normalize_llm_section(config_data: Dict[str, Any]) -> Dict[str, Any]:
    config_copy = _deepcopy_json_like(config_data or {})
    llm_block = config_copy.get("llm")

    if not isinstance(llm_block, dict):
        config_copy["llm"] = {
            "current": DEFAULT_CURRENT_LLM,
            "providers": _deepcopy_json_like(DEFAULT_LLM_PROVIDERS),
        }
        return config_copy

    raw_providers = llm_block.get("providers")
    if not isinstance(raw_providers, dict) or not raw_providers:
        config_copy["llm"] = _build_legacy_llm_section(config_copy)
        return config_copy

    providers: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_entry in raw_providers.items():
        name = str(raw_name)
        providers[name] = _ensure_llm_entry(name, raw_entry if isinstance(raw_entry, dict) else {})

    current = str(llm_block.get("current") or "").strip()
    if not current or current not in providers:
        current = next(iter(providers.keys()))

    config_copy["llm"] = {
        "current": current,
        "providers": providers,
    }
    return config_copy


def load_config(force_reload: bool = False) -> Dict[str, Any]:
    global _config
    if force_reload:
        _config = {}

    if not _config:
        if not os.path.exists(CONFIG_PATH):
            _config = _normalize_llm_section({})
        else:
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"配置文件不是合法 JSON: {CONFIG_PATH}: {e}") from e
            _config = _normalize_llm_section(loaded)
    return _config


def reload_config() -> Dict[str, Any]:
    return load_config(force_reload=True)


def _write_config(config_data: Dict[str, Any]) -> None:
    normalized = _normalize_llm_section(config_data)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
        f.write("\n")

    global _config
    _config = normalized


def save_config(config_data: Dict[str, Any]) -> Dict[str, Any]:
    _write_config(config_data)
    return load_config()


def _get_config_value(key: str) -> Optional[Any]:
    config_data = load_config()
    keys = key.split(".")
    value: Any = config_data
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


def list_llms() -> Dict[str, Dict[str, Any]]:
    llm_block = reload_config().get("llm", {})
    providers = llm_block.get("providers", {})
    return {name: dict(entry) for name, entry in providers.items()}


def get_current_llm_name() -> str:
    llm_block = reload_config().get("llm", {})
    return str(llm_block.get("current") or DEFAULT_CURRENT_LLM)


def get_llm_config(name: Optional[str] = None) -> Dict[str, Any]:
    providers = list_llms()
    llm_name = str(name or get_current_llm_name())
    if llm_name not in providers:
        raise RuntimeError(f"未找到 LLM 配置: {llm_name}")

    entry = dict(providers[llm_name])
    entry["name"] = llm_name
    return entry


def get_current_llm_config() -> Dict[str, Any]:
    return get_llm_config()


def set_current_llm(name: str) -> Dict[str, Any]:
    desired = str(name or "").strip()
    if not desired:
        raise RuntimeError("必须提供要切换的 LLM 名称。")

    config_data = reload_config()
    providers = config_data.get("llm", {}).get("providers", {})
    if desired not in providers:
        available = ", ".join(sorted(providers.keys()))
        raise RuntimeError(f"未找到 LLM 配置: {desired}. 可用项: {available}")

    config_data["llm"]["current"] = desired
    save_config(config_data)
    return get_llm_config(desired)


# 预加载配置
load_config()
