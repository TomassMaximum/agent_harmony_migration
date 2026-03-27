import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from .custom_types import ChatRequest, ChatResponse


PROVIDER_ALIASES = {
    "deepseek": "deepseek",
    "openai": "openai",
    "openai_compatible": "openai_compatible",
    "openai-compatible": "openai_compatible",
    "compatible": "openai_compatible",
}


def normalize_provider(provider: Optional[str]) -> str:
    raw = (provider or "").strip().lower()
    if not raw:
        raise RuntimeError("缺少 LLM provider 配置。")

    normalized = PROVIDER_ALIASES.get(raw)
    if normalized:
        return normalized

    return raw

class OpenAICompatibleLLM:
    def __init__(
        self,
        llm_name: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        llm_config = config.get_llm_config(llm_name)
        self.llm_name = llm_config["name"]
        self.provider = normalize_provider(provider or llm_config.get("provider"))
        self.api_key = api_key if api_key is not None else llm_config.get("api_key", "")
        self.base_url = self._resolve_base_url(base_url, llm_config)
        self.timeout = timeout if timeout is not None else llm_config.get("timeout", 120)

        if not self.api_key:
            raise RuntimeError(
                "未检测到 LLM API Key，请在 config.json 中填写：\n"
                f"llm.providers.{self.llm_name}.api_key"
            )

        if not self.base_url:
            raise RuntimeError(
                f"未检测到 provider={self.provider} 的 base_url，请在 config.json 中填写：\n"
                f"llm.providers.{self.llm_name}.base_url"
            )

    def _resolve_base_url(self, base_url: Optional[str], llm_config: Dict) -> str:
        if base_url is not None:
            return self._normalize_chat_completions_url(base_url)

        return self._normalize_chat_completions_url(llm_config.get("base_url", ""))

    def _normalize_chat_completions_url(self, raw_url: str) -> str:
        url = (raw_url or "").strip()
        if not url:
            return ""

        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        if path.endswith("/chat/completions"):
            return url.rstrip("/")

        normalized_base = url.rstrip("/")
        return f"{normalized_base}/chat/completions"

    def chat(self, req: ChatRequest) -> ChatResponse:
        payload = self._build_payload(req)
        raw = self._post_json(payload)
        return self._parse_response(raw)

    def _build_payload(self, req: ChatRequest) -> Dict:
        payload: Dict = {
            "model": req.model,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in req.messages
            ],
            "stream": req.stream,
        }

        if req.temperature is not None:
            payload["temperature"] = req.temperature

        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens

        if req.extra_body:
            payload.update(req.extra_body)

        return payload

    def _post_json(self, payload: Dict) -> Dict:
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"LLM API 请求失败(provider={self.provider})\n"
                f"HTTP {e.code} {e.reason}\n"
                f"{error_body}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络请求失败(provider={self.provider})：{e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"响应不是合法 JSON(provider={self.provider})：{e}") from e

    def _parse_response(self, raw: Dict) -> ChatResponse:
        choices = raw.get("choices") or []
        if not choices:
            raise RuntimeError(f"响应中没有 choices 字段，原始响应：{raw}")

        first = choices[0]
        message = first.get("message") or {}
        content = message.get("content", "")

        return ChatResponse(
            model=raw.get("model", ""),
            content=content,
            raw=raw,
            usage=raw.get("usage", {}),
            finish_reason=first.get("finish_reason"),
        )


def create_llm(
    llm_name: Optional[str] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> OpenAICompatibleLLM:
    llm_config = config.get_llm_config(llm_name)
    normalized = normalize_provider(provider or llm_config.get("provider"))
    return OpenAICompatibleLLM(
        llm_name=llm_config["name"],
        provider=normalized,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )


# 向后兼容旧导入名。
DeepSeekLLM = OpenAICompatibleLLM
