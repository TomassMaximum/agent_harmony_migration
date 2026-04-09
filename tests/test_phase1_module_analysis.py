import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.custom_types import ChatResponse
from agent.phase1_module_analysis import (
    Phase1ModuleAnalyzer,
    inspect_android_project,
    review_module_analysis,
)
from agent.project_memory import derive_project_memory_path


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, _req):
        if not self._responses:
            raise AssertionError("No fake responses left")
        content = self._responses.pop(0)
        return ChatResponse(model="qwen-plus", content=content, raw={})


def _create_fake_android_project(root: Path) -> None:
    (root / "settings.gradle.kts").write_text('include(":app")\ninclude(":analytics:testkitchen")\n', encoding="utf-8")
    (root / "app").mkdir()
    (root / "app" / "build.gradle").write_text(
        """
productFlavors {
    dev {
    }
    prod {
    }
}
""".strip(),
        encoding="utf-8",
    )
    manifest_dir = root / "app" / "src" / "main"
    (manifest_dir / "java" / "org" / "wikipedia" / "main").mkdir(parents=True)
    (manifest_dir / "java" / "org" / "wikipedia" / "feed").mkdir(parents=True)
    (manifest_dir / "java" / "org" / "wikipedia" / "dataclient").mkdir(parents=True)
    (manifest_dir / "java" / "org" / "wikipedia" / "settings").mkdir(parents=True)
    (manifest_dir / "java" / "org" / "wikipedia" / "WikipediaApp.kt").write_text("class WikipediaApp {}", encoding="utf-8")
    (manifest_dir / "java" / "org" / "wikipedia" / "main" / "MainActivity.kt").write_text("class MainActivity {}", encoding="utf-8")
    (manifest_dir / "java" / "org" / "wikipedia" / "feed" / "FeedFragment.kt").write_text("class FeedFragment {}", encoding="utf-8")
    (manifest_dir / "java" / "org" / "wikipedia" / "dataclient" / "Service.kt").write_text("class Service {}", encoding="utf-8")
    (manifest_dir / "java" / "org" / "wikipedia" / "settings" / "SettingsActivity.kt").write_text("class SettingsActivity {}", encoding="utf-8")
    (manifest_dir / "AndroidManifest.xml").write_text(
        """
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application>
    <activity android:name=".main.MainActivity" />
    <activity android:name=".settings.SettingsActivity" />
  </application>
</manifest>
""".strip(),
        encoding="utf-8",
    )


class Phase1ModuleAnalyzerTest(unittest.TestCase):
    def test_review_detects_uncovered_high_signal_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            target = Path(tmpdir) / "target"
            source.mkdir()
            target.mkdir()
            _create_fake_android_project(source)

            snapshot = inspect_android_project(str(source), str(target))
            data = {
                "analysis_summary": "summary",
                "module_index": [
                    {
                        "module_id": "mod_shell",
                        "name": "Shell",
                        "type": "business",
                        "description": "desc",
                        "gradle_module_refs": [":app"],
                        "package_refs": ["org.wikipedia.main"],
                        "responsibilities": ["main"],
                        "key_entrypoints": ["org.wikipedia.main.MainActivity"],
                        "evidence_refs": ["ev_gradle_app", "ev_pkg_org_wikipedia_main"],
                        "unknown_refs": [],
                    }
                ],
                "unknowns": [],
                "coverage": {
                    "covered_package_refs": ["org.wikipedia.main"],
                    "uncovered_package_refs": [],
                    "covered_gradle_module_refs": [":app"],
                    "notes": [],
                },
            }

            review = review_module_analysis(data, snapshot, unknown_threshold=60)
            self.assertFalse(review.accepted)
            self.assertTrue(any("高信号 package refs 未被模块覆盖" in issue for issue in review.issues))

    def test_analyzer_retries_and_persists_when_second_response_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            target = Path(tmpdir) / "target"
            output = Path(tmpdir) / "out"
            source.mkdir()
            target.mkdir()
            _create_fake_android_project(source)

            first = json.dumps({
                "analysis_summary": "bad",
                "module_index": [
                    {
                        "module_id": "mod_shell",
                        "name": "Shell",
                        "type": "business",
                        "description": "desc",
                        "gradle_module_refs": [":app"],
                        "package_refs": ["org.wikipedia.main"],
                        "responsibilities": ["main"],
                        "key_entrypoints": ["org.wikipedia.main.MainActivity"],
                        "evidence_refs": ["ev_gradle_app", "ev_pkg_org_wikipedia_main"],
                        "unknown_refs": [],
                    }
                ],
                "unknowns": [],
                "coverage": {
                    "covered_package_refs": ["org.wikipedia.main"],
                    "uncovered_package_refs": [],
                    "covered_gradle_module_refs": [":app"],
                    "notes": [],
                },
            }, ensure_ascii=False)

            second = json.dumps({
                "analysis_summary": "good",
                "module_index": [
                    {
                        "module_id": "mod_shell",
                        "name": "Shell",
                        "type": "business",
                        "description": "desc",
                        "gradle_module_refs": [":app"],
                        "package_refs": ["org.wikipedia.main", "org.wikipedia.__root__"],
                        "responsibilities": ["entry"],
                        "key_entrypoints": ["org.wikipedia.main.MainActivity"],
                        "evidence_refs": ["ev_gradle_app", "ev_pkg_org_wikipedia_main", "ev_pkg_org_wikipedia_root"],
                        "unknown_refs": [],
                    },
                    {
                        "module_id": "mod_feed",
                        "name": "Feed",
                        "type": "business",
                        "description": "desc",
                        "gradle_module_refs": [":app"],
                        "package_refs": ["org.wikipedia.feed"],
                        "responsibilities": ["feed"],
                        "key_entrypoints": ["org.wikipedia.feed.FeedFragment"],
                        "evidence_refs": ["ev_pkg_org_wikipedia_feed"],
                        "unknown_refs": [],
                    },
                    {
                        "module_id": "mod_data",
                        "name": "Data",
                        "type": "infrastructure",
                        "description": "desc",
                        "gradle_module_refs": [":app", ":analytics:testkitchen"],
                        "package_refs": ["org.wikipedia.dataclient"],
                        "responsibilities": ["data"],
                        "key_entrypoints": [],
                        "evidence_refs": ["ev_gradle_analytics_testkitchen", "ev_pkg_org_wikipedia_dataclient"],
                        "unknown_refs": [],
                    },
                    {
                        "module_id": "mod_settings",
                        "name": "Settings",
                        "type": "shared",
                        "description": "desc",
                        "gradle_module_refs": [":app"],
                        "package_refs": ["org.wikipedia.settings"],
                        "responsibilities": ["settings"],
                        "key_entrypoints": ["org.wikipedia.settings.SettingsActivity"],
                        "evidence_refs": ["ev_activity_settings_settingsactivity", "ev_pkg_org_wikipedia_settings"],
                        "unknown_refs": [],
                    }
                ],
                "unknowns": [],
                "coverage": {
                    "covered_package_refs": [
                        "org.wikipedia.__root__",
                        "org.wikipedia.main",
                        "org.wikipedia.feed",
                        "org.wikipedia.dataclient",
                        "org.wikipedia.settings"
                    ],
                    "uncovered_package_refs": [],
                    "covered_gradle_module_refs": [":app", ":analytics:testkitchen"],
                    "notes": [],
                },
            }, ensure_ascii=False)

            fake_llm = FakeLLM([first, second])
            with patch("agent.phase1_module_analysis.create_llm", return_value=fake_llm), patch("config.get_llm_config") as mock_get_llm_config:
                mock_get_llm_config.return_value = {
                    "name": "qwen",
                    "provider": "qwen",
                    "model": "qwen-plus",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "timeout": 120,
                }
                analyzer = Phase1ModuleAnalyzer(
                    source_project_path=str(source),
                    target_template_project_path=str(target),
                    output_project_memory_path=str(output),
                    llm_name="qwen",
                    retry_limit=2,
                    unknown_threshold=60,
                )
                result = analyzer.run()

            self.assertTrue(result["accepted"])
            self.assertEqual(result["attempt_count"], 2)
            self.assertTrue((output / "indexes" / "module_index.json").exists())
            self.assertTrue((output / "exports" / "modules.md").exists())

    def test_analyzer_defaults_output_into_target_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            target = Path(tmpdir) / "target"
            source.mkdir()
            target.mkdir()
            _create_fake_android_project(source)

            second = json.dumps({
                "analysis_summary": "good",
                "module_index": [
                    {
                        "module_id": "mod_shell",
                        "name": "Shell",
                        "type": "business",
                        "description": "desc",
                        "gradle_module_refs": [":app"],
                        "package_refs": ["org.wikipedia.main", "org.wikipedia.__root__"],
                        "responsibilities": ["entry"],
                        "key_entrypoints": ["org.wikipedia.main.MainActivity"],
                        "evidence_refs": ["ev_gradle_app", "ev_pkg_org_wikipedia_main", "ev_pkg_org_wikipedia_root"],
                        "unknown_refs": [],
                    },
                    {
                        "module_id": "mod_feed",
                        "name": "Feed",
                        "type": "business",
                        "description": "desc",
                        "gradle_module_refs": [":app"],
                        "package_refs": ["org.wikipedia.feed"],
                        "responsibilities": ["feed"],
                        "key_entrypoints": ["org.wikipedia.feed.FeedFragment"],
                        "evidence_refs": ["ev_pkg_org_wikipedia_feed"],
                        "unknown_refs": [],
                    },
                    {
                        "module_id": "mod_data",
                        "name": "Data",
                        "type": "infrastructure",
                        "description": "desc",
                        "gradle_module_refs": [":app", ":analytics:testkitchen"],
                        "package_refs": ["org.wikipedia.dataclient"],
                        "responsibilities": ["data"],
                        "key_entrypoints": [],
                        "evidence_refs": ["ev_gradle_analytics_testkitchen", "ev_pkg_org_wikipedia_dataclient"],
                        "unknown_refs": [],
                    },
                    {
                        "module_id": "mod_settings",
                        "name": "Settings",
                        "type": "shared",
                        "description": "desc",
                        "gradle_module_refs": [":app"],
                        "package_refs": ["org.wikipedia.settings"],
                        "responsibilities": ["settings"],
                        "key_entrypoints": ["org.wikipedia.settings.SettingsActivity"],
                        "evidence_refs": ["ev_activity_settings_settingsactivity", "ev_pkg_org_wikipedia_settings"],
                        "unknown_refs": [],
                    }
                ],
                "unknowns": [],
                "coverage": {
                    "covered_package_refs": [
                        "org.wikipedia.__root__",
                        "org.wikipedia.main",
                        "org.wikipedia.feed",
                        "org.wikipedia.dataclient",
                        "org.wikipedia.settings"
                    ],
                    "uncovered_package_refs": [],
                    "covered_gradle_module_refs": [":app", ":analytics:testkitchen"],
                    "notes": [],
                },
            }, ensure_ascii=False)

            fake_llm = FakeLLM([second])
            with patch("agent.phase1_module_analysis.create_llm", return_value=fake_llm), patch("config.get_llm_config") as mock_get_llm_config:
                mock_get_llm_config.return_value = {
                    "name": "qwen",
                    "provider": "qwen",
                    "model": "qwen-plus",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "timeout": 120,
                }
                analyzer = Phase1ModuleAnalyzer(
                    source_project_path=str(source),
                    target_template_project_path=str(target),
                    llm_name="qwen",
                    retry_limit=1,
                    unknown_threshold=60,
                )
                result = analyzer.run()

            expected_output = Path(derive_project_memory_path(str(target)))
            self.assertTrue(result["accepted"])
            self.assertEqual(str(expected_output), result["project_memory_path"])
            self.assertTrue((expected_output / "indexes" / "module_index.json").exists())


if __name__ == "__main__":
    unittest.main()
