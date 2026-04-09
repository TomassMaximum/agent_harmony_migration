import tempfile
import unittest
from pathlib import Path

from agent.project_memory import (
    DEFAULT_PROJECT_MEMORY_RELPATH,
    ProjectMemoryStore,
    ProjectMemoryValidationError,
    create_builder_job,
    create_project_overview,
    derive_project_memory_path,
    resolve_project_memory_path,
    validate_builder_job,
    validate_project_overview,
)


class ProjectMemoryStoreTest(unittest.TestCase):
    def test_init_minimum_files_creates_expected_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project_memory"
            store = ProjectMemoryStore(str(root))
            builder_job = create_builder_job(
                source_project_path="/tmp/source",
                target_template_project_path="/tmp/target",
                output_project_memory_path=str(root),
                llm_name="qwen",
                unknown_threshold=60,
            )
            overview = create_project_overview(
                source_project_path="/tmp/source",
                target_template_project_path="/tmp/target",
                high_level_goal="goal",
            )

            store.init_minimum_files(builder_job, overview)

            self.assertTrue((root / "builder_job.json").exists())
            self.assertTrue((root / "project_overview.json").exists())
            self.assertTrue((root / "coverage_status.json").exists())
            self.assertTrue((root / "indexes" / "module_index.json").exists())
            self.assertTrue((root / "unknowns" / "queue.json").exists())
            self.assertTrue((root / "skeletons" / "implementation_index.json").exists())


class ProjectMemoryValidationTest(unittest.TestCase):
    def test_derive_project_memory_path_points_into_target_project(self) -> None:
        target_root = "/tmp/wiki"
        expected = str(Path(target_root) / DEFAULT_PROJECT_MEMORY_RELPATH)
        self.assertEqual(expected, derive_project_memory_path(target_root))

    def test_resolve_project_memory_path_prefers_explicit_path(self) -> None:
        self.assertEqual(
            "/tmp/custom-memory",
            resolve_project_memory_path("/tmp/wiki", "/tmp/custom-memory"),
        )

    def test_validate_builder_job_rejects_bad_threshold(self) -> None:
        builder_job = create_builder_job(
            source_project_path="/tmp/source",
            target_template_project_path="/tmp/target",
            output_project_memory_path="/tmp/out",
            llm_name="qwen",
            unknown_threshold=60,
        )
        builder_job["confirmation_policy"]["unknown_score_threshold"] = 200

        with self.assertRaises(ProjectMemoryValidationError):
            validate_builder_job(builder_job)

    def test_validate_project_overview_accepts_basic_shape(self) -> None:
        overview = create_project_overview(
            source_project_path="/tmp/source",
            target_template_project_path="/tmp/target",
            high_level_goal="goal",
        )
        validated = validate_project_overview(overview)
        self.assertEqual(validated["high_level_goal"], "goal")


if __name__ == "__main__":
    unittest.main()
