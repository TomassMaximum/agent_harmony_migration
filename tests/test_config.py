import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config


class LLMStateConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config_path = os.path.join(self.tmpdir.name, "config.json")

    def write_config(self, payload) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def test_set_current_llm_updates_config_file(self) -> None:
        self.write_config(
            {
                "agent": {"max_steps": 80, "root": "."},
                "llm": {
                    "current": "deepseek",
                    "providers": {
                        "deepseek": {
                            "provider": "deepseek",
                            "model": "deepseek-chat",
                            "api_key": "k1",
                            "base_url": "",
                            "timeout": 120,
                        },
                        "openai": {
                            "provider": "openai",
                            "model": "gpt-4.1",
                            "api_key": "k2",
                            "base_url": "",
                            "timeout": 120,
                        },
                    },
                },
            }
        )

        with patch.object(config, "CONFIG_PATH", self.config_path):
            config.reload_config()
            selected = config.set_current_llm("openai")

            self.assertEqual(selected["name"], "openai")
            self.assertEqual(config.get_current_llm_name(), "openai")

            with open(self.config_path, "r", encoding="utf-8") as f:
                persisted = json.load(f)
        config.reload_config()

        self.assertEqual(persisted["llm"]["current"], "openai")

    def test_load_config_migrates_legacy_llm_shape(self) -> None:
        self.write_config(
            {
                "agent": {
                    "model": "deepseek-chat",
                    "max_steps": 80,
                    "root": ".",
                },
                "llm": {
                    "provider": "deepseek",
                    "api_key": "legacy-key",
                    "base_url": "",
                    "timeout": 120,
                },
            }
        )

        with patch.object(config, "CONFIG_PATH", self.config_path):
            current = config.reload_config()
            llm_entry = config.get_current_llm_config()
        config.reload_config()

        self.assertEqual(current["llm"]["current"], "deepseek")
        self.assertIn("providers", current["llm"])
        self.assertEqual(llm_entry["model"], "deepseek-chat")
        self.assertEqual(llm_entry["api_key"], "legacy-key")


if __name__ == "__main__":
    unittest.main()
