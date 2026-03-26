import tempfile
import unittest
from pathlib import Path

from tools.read_file import ReadFileTool
from tools.run_command import RunCommandTool
from tools.search_text import SearchTextTool


class ReadFileToolTest(unittest.TestCase):
    def test_read_file_respects_max_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("abcdef", encoding="utf-8")

            tool = ReadFileTool()
            result = tool.run(path=str(path), max_chars=3)

            self.assertTrue(result.ok)
            self.assertEqual(result.content, "abc")
            self.assertTrue(result.meta["truncated"])


class SearchTextToolTest(unittest.TestCase):
    def test_search_text_returns_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.py").write_text("needle here\n", encoding="utf-8")
            (root / "b.txt").write_text("no match\n", encoding="utf-8")

            tool = SearchTextTool()
            result = tool.run(root=str(root), keyword="needle", file_extensions=[".py"])

            self.assertTrue(result.ok)
            self.assertIn("a.py:1: needle here", result.content)
            self.assertEqual(result.meta["count"], 1)
            self.assertFalse(result.meta["truncated"])


class RunCommandToolTest(unittest.TestCase):
    def test_run_command_returns_exit_code_meta(self) -> None:
        tool = RunCommandTool()
        result = tool.run(command="printf 'ok'")

        self.assertTrue(result.ok)
        self.assertIn("[exit_code] 0", result.content)
        self.assertEqual(result.meta["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
