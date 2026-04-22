import json
import tempfile
import unittest
from pathlib import Path

from agent.project_memory import ProjectMemoryStore, create_builder_job, create_project_overview
from agent.unknown_queue import (
    build_review_items,
    defer_review_item,
    load_confirmation_context,
    record_decision,
    set_confirmation_threshold,
)


def _seed_project_memory(root: Path) -> Path:
    pm = root / "project_memory"
    store = ProjectMemoryStore(str(pm))
    store.init_minimum_files(
        create_builder_job(
            source_project_path="/tmp/source",
            target_template_project_path="/tmp/target",
            output_project_memory_path=str(pm),
            llm_name="qwen",
            unknown_threshold=60,
        ),
        create_project_overview(
            source_project_path="/tmp/source",
            target_template_project_path="/tmp/target",
            high_level_goal="goal",
        ),
    )
    queue = [
        {
            "unknown_id": "unk_build_variant",
            "title": "Flavor gating",
            "description": "desc",
            "category": "build_variant",
            "evidence_refs": ["ev_flavor_dev"],
            "candidate_options": ["annotate", "ignore"],
            "recommended_option": "annotate",
            "uncertainty_score": 90,
            "severity_score": 75,
            "impact_scope": ["build_variant", "feature_coverage"],
            "needs_user_confirmation": True,
            "status": "open",
            "recheck_count": 0,
            "decision_score": 90,
        },
        {
            "unknown_id": "unk_page_attach_search_1",
            "title": "SearchResultsScreen 页面归属待确认",
            "description": "desc",
            "category": "page_mapping",
            "evidence_refs": ["app/src/main/java/org/wikipedia/search/SearchResultsScreen.kt"],
            "candidate_options": ["page_search_main", "page_search_onboarding"],
            "recommended_option": "page_search_main",
            "uncertainty_score": 65,
            "severity_score": 45,
            "impact_scope": ["compose_screen:org.wikipedia.search.SearchResultsScreen"],
            "needs_user_confirmation": True,
            "status": "open",
            "recheck_count": 0,
            "decision_score": 65,
        },
        {
            "unknown_id": "unk_page_attach_search_2",
            "title": "HybridSearchResultsScreen 页面归属待确认",
            "description": "desc",
            "category": "page_mapping",
            "evidence_refs": ["app/src/main/java/org/wikipedia/search/HybridSearchResultsScreen.kt"],
            "candidate_options": ["page_search_main", "page_search_onboarding"],
            "recommended_option": "page_search_main",
            "uncertainty_score": 65,
            "severity_score": 45,
            "impact_scope": ["compose_screen:org.wikipedia.search.HybridSearchResultsScreen"],
            "needs_user_confirmation": True,
            "status": "open",
            "recheck_count": 0,
            "decision_score": 65,
        },
        {
            "unknown_id": "unk_low_score",
            "title": "Low score noise",
            "description": "desc",
            "category": "page_mapping",
            "evidence_refs": ["app/src/main/java/org/wikipedia/feed/FeedFragment.kt"],
            "candidate_options": ["page_feed"],
            "recommended_option": "page_feed",
            "uncertainty_score": 20,
            "severity_score": 10,
            "impact_scope": ["fragment:org.wikipedia.feed.FeedFragment"],
            "needs_user_confirmation": False,
            "status": "open",
            "recheck_count": 0,
            "decision_score": 20,
        },
    ]
    store.write_json("unknowns/queue.json", queue)
    return pm


class UnknownQueueTest(unittest.TestCase):
    def test_build_review_items_groups_page_mapping_unknowns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = _seed_project_memory(Path(tmpdir))
            _store, builder_job, queue, _decisions = load_confirmation_context(str(pm))
            result = build_review_items(queue, threshold=60, limit=10)

            self.assertEqual(2, result["returned_items"])
            cluster_items = [item for item in result["review_items"] if item["item_type"] == "cluster"]
            self.assertEqual(1, len(cluster_items))
            self.assertEqual(2, cluster_items[0]["item_count"])
            self.assertEqual(
                ["unk_page_attach_search_1", "unk_page_attach_search_2"],
                cluster_items[0]["unknown_ids"],
            )
            self.assertEqual(60, builder_job["confirmation_policy"]["unknown_score_threshold"])

    def test_record_decision_updates_queue_and_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = _seed_project_memory(Path(tmpdir))
            _store, _builder_job, queue, _decisions = load_confirmation_context(str(pm))
            review_batch = build_review_items(queue, threshold=60, limit=10)
            cluster_item = next(item for item in review_batch["review_items"] if item["item_type"] == "cluster")

            result = record_decision(
                project_memory_path=str(pm),
                item_id=cluster_item["review_item_id"],
                choice="recommended",
                rationale="search package pages should attach to main search page",
            )

            self.assertEqual(2, result["updated_unknown_count"])
            store = ProjectMemoryStore(str(pm))
            updated_queue = store.read_json("unknowns/queue.json")
            updated_items = {
                item["unknown_id"]: item
                for item in updated_queue
                if item["unknown_id"] in {"unk_page_attach_search_1", "unk_page_attach_search_2"}
            }
            self.assertTrue(all(item["status"] == "resolved" for item in updated_items.values()))
            self.assertTrue(all(item["chosen_option"] == "page_search_main" for item in updated_items.values()))

            decisions = store.read_json("unknowns/decisions.json")
            self.assertEqual(2, len(decisions))
            self.assertTrue(all(item["decision_type"] == "confirmed" for item in decisions))

    def test_defer_review_item_marks_unknowns_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = _seed_project_memory(Path(tmpdir))
            _store, _builder_job, queue, _decisions = load_confirmation_context(str(pm))
            review_batch = build_review_items(queue, threshold=60, limit=10)
            first_item = review_batch["review_items"][0]

            result = defer_review_item(
                project_memory_path=str(pm),
                item_id=first_item["review_item_id"],
                rationale="wait until flow analysis",
            )

            self.assertGreaterEqual(result["updated_unknown_count"], 1)
            store = ProjectMemoryStore(str(pm))
            queue_after = store.read_json("unknowns/queue.json")
            touched = [item for item in queue_after if item["unknown_id"] in set(first_item["unknown_ids"])]
            self.assertTrue(all(item["status"] == "deferred" for item in touched))

    def test_set_confirmation_threshold_updates_builder_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = _seed_project_memory(Path(tmpdir))
            result = set_confirmation_threshold(str(pm), 72)
            self.assertEqual(72, result["unknown_score_threshold"])
            builder_job = json.loads((pm / "builder_job.json").read_text(encoding="utf-8"))
            self.assertEqual(72, builder_job["confirmation_policy"]["unknown_score_threshold"])


if __name__ == "__main__":
    unittest.main()
