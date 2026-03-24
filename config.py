import json
import os
from typing import Any, Dict

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

_config: Dict[str, Any] = {}


def load_config() -> Dict[str, Any]:
    global _config
    if not _config:
        if not os.path.exists(CONFIG_PATH):
            # 如果配置文件不存在，返回空字典，后续使用默认值
            _config = {}
        else:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _config = json.load(f)
    return _config


def get(key: str, default: Any = None) -> Any:
    config = load_config()
    keys = key.split(".")
    value = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


# 预加载配置
load_config()
