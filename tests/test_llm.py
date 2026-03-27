import unittest
from unittest.mock import patch

from agent.llm import OpenAICompatibleLLM, normalize_provider


class LLMConfigTest(unittest.TestCase):
    def test_normalize_provider_accepts_alias(self) -> None:
        self.assertEqual(normalize_provider("openai-compatible"), "openai_compatible")

    def test_normalize_provider_accepts_custom_provider_name(self) -> None:
        self.assertEqual(normalize_provider("qwen"), "qwen")

    def test_provider_requires_explicit_base_url(self) -> None:
        llm_config = {
            "name": "openai",
            "provider": "openai",
            "model": "gpt-4.1",
            "api_key": "test-key",
            "base_url": "",
            "timeout": 120,
        }

        with patch("config.get_llm_config", return_value=llm_config):
            with self.assertRaises(RuntimeError) as ctx:
                OpenAICompatibleLLM(llm_name="openai")

        self.assertIn("base_url", str(ctx.exception))

    def test_openai_compatible_requires_explicit_base_url(self) -> None:
        llm_config = {
            "name": "custom",
            "provider": "openai_compatible",
            "model": "custom-model",
            "api_key": "test-key",
            "base_url": "",
            "timeout": 120,
        }

        with patch("config.get_llm_config", return_value=llm_config):
            with self.assertRaises(RuntimeError) as ctx:
                OpenAICompatibleLLM(llm_name="custom")

        self.assertIn("base_url", str(ctx.exception))

    def test_sdk_style_base_url_is_normalized_to_chat_completions_endpoint(self) -> None:
        llm_config = {
            "name": "qwen",
            "provider": "qwen",
            "model": "qwen-plus",
            "api_key": "test-key",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "timeout": 120,
        }

        with patch("config.get_llm_config", return_value=llm_config):
            client = OpenAICompatibleLLM(llm_name="qwen")

        self.assertEqual(
            client.base_url,
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )

    def test_full_chat_completions_url_is_kept(self) -> None:
        llm_config = {
            "name": "deepseek",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key": "test-key",
            "base_url": "https://api.deepseek.com/chat/completions",
            "timeout": 120,
        }

        with patch("config.get_llm_config", return_value=llm_config):
            client = OpenAICompatibleLLM(llm_name="deepseek")

        self.assertEqual(client.base_url, "https://api.deepseek.com/chat/completions")


if __name__ == "__main__":
    unittest.main()
