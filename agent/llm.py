import json
import os
import sys
import urllib.error
import urllib.request
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from .custom_types import ChatRequest, ChatResponse


class DeepSeekLLM:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        # 优先级：参数 > 环境变量 > 配置文件 > 默认值
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY") or config.get("llm.api_key", "")
        self.base_url = base_url if base_url is not None else config.get("llm.base_url", "https://api.deepseek.com/chat/completions")
        self.timeout = timeout if timeout is not None else config.get("llm.timeout", 120)

        if not self.api_key:
            raise RuntimeError(
                '未检测到 DeepSeek API Key，请设置环境变量：\n'
                'export DEEPSEEK_API_KEY="你的 key"'
            )

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
                f"DeepSeek API 请求失败\n"
                f"HTTP {e.code} {e.reason}\n"
                f"{error_body}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络请求失败：{e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"响应不是合法 JSON：{e}") from e

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
