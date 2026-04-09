import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.custom_types import ChatResponse
from agent.page_analysis import (
    Stage2PageAnalyzer,
    enrich_module_index_with_package_bindings,
    extract_declared_base_types,
    extract_ui_symbols,
    inspect_page_analysis_snapshot,
    resolve_module_ids_for_package,
    review_page_analysis,
)
from agent.project_memory import ProjectMemoryStore, create_builder_job, create_project_overview


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, _req):
        if not self._responses:
            raise AssertionError("No fake responses left")
        return ChatResponse(model="qwen-plus", content=self._responses.pop(0), raw={})


def _create_fake_project(root: Path) -> None:
    (root / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
    (root / "app" / "src" / "main" / "java" / "org" / "wikipedia" / "main").mkdir(parents=True)
    (root / "app" / "src" / "main" / "java" / "org" / "wikipedia" / "search").mkdir(parents=True)
    (root / "app" / "src" / "main" / "java" / "org" / "wikipedia" / "settings").mkdir(parents=True)
    (root / "app" / "src" / "androidTest" / "java" / "org" / "wikipedia" / "test").mkdir(parents=True)
    (root / "app" / "src" / "main" / "AndroidManifest.xml").write_text(
        """
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application>
    <activity android:name=".main.MainActivity" />
    <activity android:name=".search.SearchActivity" />
    <activity android:name=".settings.SettingsActivity" />
  </application>
</manifest>
""".strip(),
        encoding="utf-8",
    )
    (root / "app" / "src" / "main" / "java" / "org" / "wikipedia" / "main" / "MainActivity.kt").write_text(
        "class MainActivity : BaseActivity() {}\nclass HomeFragment : Fragment() {}",
        encoding="utf-8",
    )
    (root / "app" / "src" / "main" / "java" / "org" / "wikipedia" / "search" / "SearchActivity.kt").write_text(
        "class SearchActivity : BaseActivity() {}\nclass SearchFragment : Fragment() {}\nfun SearchResultsScreen() {}",
        encoding="utf-8",
    )
    (root / "app" / "src" / "main" / "java" / "org" / "wikipedia" / "settings" / "SettingsActivity.kt").write_text(
        "class SettingsActivity : BaseActivity() {}\nclass SettingsDialog : DialogFragment() {}",
        encoding="utf-8",
    )
    (root / "app" / "src" / "androidTest" / "java" / "org" / "wikipedia" / "test" / "BaseTest.kt").write_text(
        "class BaseTest {}",
        encoding="utf-8",
    )


class PageAnalysisTest(unittest.TestCase):
    def test_extract_declared_base_types_ignores_generic_noise(self) -> None:
        base_types = extract_declared_base_types(" FragmentStateAdapter<ItemFragment>(fragment)")
        self.assertEqual(["FragmentStateAdapter"], base_types)

    def test_extract_ui_symbols_prefers_dialog_over_fragment(self) -> None:
        symbols = extract_ui_symbols("class SettingsDialog : DialogFragment() {}")
        self.assertIn(("dialog", "SettingsDialog"), symbols)
        self.assertNotIn(("fragment", "SettingsDialog"), symbols)

    def test_extract_ui_symbols_ignores_adapter_with_fragment_generic(self) -> None:
        symbols = extract_ui_symbols(
            "class DescriptionPagerAdapter : FragmentStateAdapter<ItemFragment>(fragment) {}"
        )
        self.assertEqual([], symbols)

    def test_extract_ui_symbols_ignores_constructor_parameter_activity_type(self) -> None:
        symbols = extract_ui_symbols(
            "class CaptchaHandler(private val activity: AppCompatActivity, private val name: String)"
        )
        self.assertEqual([], symbols)

    def test_resolve_module_ids_for_package_uses_longest_prefix(self) -> None:
        mapping = {
            "org.wikipedia.feed": ["mod_feed"],
            "org.wikipedia.feed.news": ["mod_feed_news"],
            "org.wikipedia.__root__": ["mod_root"],
        }
        self.assertEqual(
            ["mod_feed_news"],
            resolve_module_ids_for_package("org.wikipedia.feed.news.detail", mapping),
        )

    def test_enrich_module_index_adds_package_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_fake_project(root)
            module_index = [
                {
                    "module_id": "mod_business_home",
                    "name": "Home",
                    "type": "business",
                    "description": "desc",
                    "gradle_module_refs": [":app"],
                    "package_refs": ["org.wikipedia.main", "org.wikipedia.search"],
                    "responsibilities": ["r"],
                    "key_entrypoints": ["a"],
                    "evidence_refs": ["e1"],
                    "unknown_refs": [],
                }
            ]
            upgraded = enrich_module_index_with_package_bindings(str(root), module_index)
            self.assertIn("package_bindings", upgraded[0])
            self.assertEqual(upgraded[0]["package_bindings"][0]["gradle_module_ref"], ":app")

    def test_review_detects_missing_manifest_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_fake_project(root)
            pm = root / "project_memory"
            store = ProjectMemoryStore(str(pm))
            store.init_minimum_files(
                create_builder_job(str(root), "/tmp/target", str(pm), "qwen", 60),
                create_project_overview(str(root), "/tmp/target", "goal"),
            )
            store.write_json("indexes/module_index.json", [
                {
                    "module_id": "mod_business_home",
                    "name": "Home",
                    "type": "business",
                    "description": "desc",
                    "gradle_module_refs": [":app"],
                    "package_refs": ["org.wikipedia.main", "org.wikipedia.search", "org.wikipedia.settings"],
                    "responsibilities": ["r"],
                    "key_entrypoints": ["a"],
                    "evidence_refs": ["e1"],
                    "unknown_refs": [],
                }
            ])
            snapshot = inspect_page_analysis_snapshot(str(root), str(pm))
            data = {
                "analysis_summary": "summary",
                "page_index": [
                    {
                        "page_id": "page_home",
                        "name": "Home",
                        "page_kind": "activity",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.main.MainActivity"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": ["activity:org.wikipedia.main.MainActivity"],
                        "route_hint": "home",
                        "user_visible": True,
                        "summary": "home",
                        "unknown_refs": [],
                    }
                ],
                "ignored_components": [],
                "unknowns": [],
                "coverage": {
                    "covered_component_refs": ["activity:org.wikipedia.main.MainActivity"],
                    "ignored_component_refs": [],
                    "missing_component_refs": [],
                    "notes": [],
                },
            }
            review = review_page_analysis(data, snapshot, 60)
            self.assertFalse(review.accepted)
            self.assertTrue(any("manifest activities 未被页面覆盖" in issue for issue in review.issues))

    def test_stage2_retries_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _create_fake_project(root)
            pm = root / "project_memory"
            store = ProjectMemoryStore(str(pm))
            store.init_minimum_files(
                create_builder_job(str(root), "/tmp/target", str(pm), "qwen", 60),
                create_project_overview(str(root), "/tmp/target", "goal"),
            )
            store.write_json("indexes/module_index.json", [
                {
                    "module_id": "mod_business_home",
                    "name": "Home",
                    "type": "business",
                    "description": "desc",
                    "gradle_module_refs": [":app"],
                    "package_refs": ["org.wikipedia.main", "org.wikipedia.search", "org.wikipedia.settings"],
                    "responsibilities": ["r"],
                    "key_entrypoints": ["a"],
                    "evidence_refs": ["e1"],
                    "unknown_refs": [],
                }
            ])

            first = json.dumps({
                "analysis_summary": "bad",
                "page_index": [],
                "ignored_components": [],
                "unknowns": [],
                "coverage": {"covered_component_refs": [], "ignored_component_refs": [], "missing_component_refs": [], "notes": []},
            }, ensure_ascii=False)
            second = json.dumps({
                "analysis_summary": "good",
                "page_index": [
                    {
                        "page_id": "page_home",
                        "name": "Home",
                        "page_kind": "activity",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.main.MainActivity"],
                        "supporting_component_refs": ["fragment:org.wikipedia.main.HomeFragment"],
                        "entry_activity_refs": ["activity:org.wikipedia.main.MainActivity"],
                        "route_hint": "home",
                        "user_visible": True,
                        "summary": "home",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_search",
                        "name": "Search",
                        "page_kind": "activity",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.search.SearchActivity"],
                        "supporting_component_refs": [
                            "fragment:org.wikipedia.search.SearchFragment",
                            "compose_screen:org.wikipedia.search.SearchResultsScreen"
                        ],
                        "entry_activity_refs": ["activity:org.wikipedia.search.SearchActivity"],
                        "route_hint": "search",
                        "user_visible": True,
                        "summary": "search",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_settings",
                        "name": "Settings",
                        "page_kind": "settings",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.settings.SettingsActivity"],
                        "supporting_component_refs": ["dialog:org.wikipedia.settings.SettingsDialog"],
                        "entry_activity_refs": ["activity:org.wikipedia.settings.SettingsActivity"],
                        "route_hint": "settings",
                        "user_visible": True,
                        "summary": "settings",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_home_fragment",
                        "name": "Home Fragment Host",
                        "page_kind": "fragment_page",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["fragment:org.wikipedia.main.HomeFragment"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": ["activity:org.wikipedia.main.MainActivity"],
                        "route_hint": "home_fragment",
                        "user_visible": True,
                        "summary": "fragment host",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_search_fragment",
                        "name": "Search Fragment Host",
                        "page_kind": "fragment_page",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["fragment:org.wikipedia.search.SearchFragment"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": ["activity:org.wikipedia.search.SearchActivity"],
                        "route_hint": "search_fragment",
                        "user_visible": True,
                        "summary": "fragment host",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_search_compose",
                        "name": "Search Results Compose",
                        "page_kind": "compose_screen",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["compose_screen:org.wikipedia.search.SearchResultsScreen"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": ["activity:org.wikipedia.search.SearchActivity"],
                        "route_hint": "search_results",
                        "user_visible": True,
                        "summary": "compose screen",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_settings_dialog",
                        "name": "Settings Dialog",
                        "page_kind": "dialog",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["dialog:org.wikipedia.settings.SettingsDialog"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": ["activity:org.wikipedia.settings.SettingsActivity"],
                        "route_hint": "settings_dialog",
                        "user_visible": True,
                        "summary": "dialog",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_overview",
                        "name": "Page Overview",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.main.MainActivity"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "overview",
                        "user_visible": False,
                        "summary": "overview",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_overview_search",
                        "name": "Page Overview Search",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.search.SearchActivity"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "overview_search",
                        "user_visible": False,
                        "summary": "overview search",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_overview_settings",
                        "name": "Page Overview Settings",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.settings.SettingsActivity"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "overview_settings",
                        "user_visible": False,
                        "summary": "overview settings",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_1",
                        "name": "Misc 1",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["fragment:org.wikipedia.main.HomeFragment"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc1",
                        "user_visible": False,
                        "summary": "misc1",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_2",
                        "name": "Misc 2",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["dialog:org.wikipedia.settings.SettingsDialog"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc2",
                        "user_visible": False,
                        "summary": "misc2",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_3",
                        "name": "Misc 3",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["compose_screen:org.wikipedia.search.SearchResultsScreen"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc3",
                        "user_visible": False,
                        "summary": "misc3",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_4",
                        "name": "Misc 4",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.main.MainActivity"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc4",
                        "user_visible": False,
                        "summary": "misc4",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_5",
                        "name": "Misc 5",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.search.SearchActivity"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc5",
                        "user_visible": False,
                        "summary": "misc5",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_6",
                        "name": "Misc 6",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["activity:org.wikipedia.settings.SettingsActivity"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc6",
                        "user_visible": False,
                        "summary": "misc6",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_7",
                        "name": "Misc 7",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["fragment:org.wikipedia.search.SearchFragment"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc7",
                        "user_visible": False,
                        "summary": "misc7",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_8",
                        "name": "Misc 8",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["fragment:org.wikipedia.main.HomeFragment"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc8",
                        "user_visible": False,
                        "summary": "misc8",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_9",
                        "name": "Misc 9",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["dialog:org.wikipedia.settings.SettingsDialog"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc9",
                        "user_visible": False,
                        "summary": "misc9",
                        "unknown_refs": [],
                    },
                    {
                        "page_id": "page_support_misc_10",
                        "name": "Misc 10",
                        "page_kind": "support",
                        "module_ids": ["mod_business_home"],
                        "primary_component_refs": ["compose_screen:org.wikipedia.search.SearchResultsScreen"],
                        "supporting_component_refs": [],
                        "entry_activity_refs": [],
                        "route_hint": "misc10",
                        "user_visible": False,
                        "summary": "misc10",
                        "unknown_refs": [],
                    }
                ],
                "ignored_components": [],
                "unknowns": [],
                "coverage": {
                    "covered_component_refs": [],
                    "ignored_component_refs": [],
                    "missing_component_refs": [],
                    "notes": [],
                },
            }, ensure_ascii=False)

            fake_llm = FakeLLM([first, second])
            with patch("agent.page_analysis.create_llm", return_value=fake_llm), patch("config.get_llm_config") as mock_get_llm_config:
                mock_get_llm_config.return_value = {
                    "name": "qwen",
                    "provider": "qwen",
                    "model": "qwen-plus",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "timeout": 120,
                }
                analyzer = Stage2PageAnalyzer(
                    source_project_path=str(root),
                    project_memory_path=str(pm),
                    llm_name="qwen",
                    retry_limit=2,
                    unknown_threshold=60,
                )
                result = analyzer.run()
            self.assertTrue(result["accepted"])
            self.assertTrue((pm / "indexes" / "page_index.json").exists())
            self.assertTrue((pm / "exports" / "pages.md").exists())


if __name__ == "__main__":
    unittest.main()
