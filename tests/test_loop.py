import os
import tempfile
import unittest
from unittest.mock import patch

from agent.custom_types import ChatResponse
from agent.events import AgentEvent
from agent.loop import AgentLoop
from tools.base import ToolResult


class FakeLLM:
    def chat(self, _req):
        raise AssertionError("chat() should be stubbed in each test")


class AgentLoopStopReasonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = self.tmpdir.name
        self.chat_path = os.path.join(self.root, "chats")
        self.session_path = os.path.join(self.root, "sessions")

        patcher = patch("agent.loop.create_llm", return_value=FakeLLM())
        self.mock_llm_cls = patcher.start()
        self.addCleanup(patcher.stop)

    def make_agent(self) -> AgentLoop:
        with patch("config.get") as mock_get, patch("config.get_llm_config") as mock_get_llm_config:
            def fake_get(key, default=None):
                mapping = {
                    "agent.session_storage_path": self.session_path,
                    "agent.chat_storage_path": self.chat_path,
                    "agent.root": self.root,
                    "agent.max_steps": 5,
                }
                return mapping.get(key, default)

            mock_get.side_effect = fake_get
            mock_get_llm_config.return_value = {
                "name": "deepseek",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": "test-key",
                "base_url": "",
                "timeout": 120,
            }
            agent = AgentLoop(root=self.root, max_steps=5)
            agent.start_session("test task", load_existing=False, inject_current_chat_memory=False)
            return agent

    def test_run_until_stop_final(self) -> None:
        agent = self.make_agent()
        state = {"n": 0}

        def fake_step_once():
            state["n"] += 1
            if state["n"] == 1:
                return [AgentEvent(type="thought", step=1, content="thinking")]
            return [AgentEvent(type="final", step=2, content="done")]

        agent.step_once = fake_step_once
        result = agent.run_until_stop(max_steps=5)

        self.assertEqual(result.stop_reason, "final")
        self.assertEqual(result.final_answer, "done")
        self.assertEqual(result.step_count, 2)

    def test_run_until_stop_max_steps(self) -> None:
        agent = self.make_agent()
        agent.step_once = lambda: [AgentEvent(type="thought", step=1, content="looping")]

        result = agent.run_until_stop(max_steps=2)

        self.assertEqual(result.stop_reason, "max_steps")
        self.assertEqual(result.step_count, 2)

    def test_run_until_stop_llm_error(self) -> None:
        agent = self.make_agent()
        agent.llm.chat = lambda _req: (_ for _ in ()).throw(RuntimeError("network boom"))

        result = agent.run_until_stop(max_steps=3)

        self.assertEqual(result.stop_reason, "llm_error")
        self.assertIn("模型请求失败", result.error_message)
        self.assertEqual(result.step_count, 1)

    def test_run_until_stop_invalid_model_output(self) -> None:
        agent = self.make_agent()
        agent.llm.chat = lambda _req: ChatResponse(model="x", content="not json", raw={})

        result = agent.run_until_stop(max_steps=3)

        self.assertEqual(result.stop_reason, "invalid_model_output")
        self.assertIn("模型输出不是合法 JSON", result.error_message)
        self.assertEqual(result.step_count, 1)

    def test_run_until_stop_tool_error(self) -> None:
        agent = self.make_agent()
        agent.llm.chat = lambda _req: ChatResponse(
            model="x",
            content='{"thought":"x","action":"tool","tool_name":"list_dir","tool_args":{"path":"."},"final_answer":""}',
            raw={},
        )
        agent.registry["list_dir"].run = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("tool boom"))

        result = agent.run_until_stop(max_steps=3)

        self.assertEqual(result.stop_reason, "tool_error")
        self.assertIn("工具 list_dir 执行异常", result.error_message)
        self.assertEqual(result.step_count, 1)

    def test_run_until_stop_accepts_action_as_tool_name(self) -> None:
        agent = self.make_agent()
        agent.llm.chat = lambda _req: ChatResponse(
            model="x",
            content='{"thought":"x","action":"list_dir","tool_name":"list_dir","tool_args":{"path":"."},"final_answer":""}',
            raw={},
        )
        agent.registry["list_dir"].run = lambda **kwargs: ToolResult(ok=True, content="done", meta={})

        result = agent.run_until_stop(max_steps=1)

        self.assertEqual(result.stop_reason, "max_steps")

    def test_run_until_stop_accepts_missing_action_when_tool_name_present(self) -> None:
        agent = self.make_agent()
        agent.llm.chat = lambda _req: ChatResponse(
            model="x",
            content='{"thought":"x","tool_name":"list_dir","tool_args":{"path":"."},"final_answer":""}',
            raw={},
        )
        agent.registry["list_dir"].run = lambda **kwargs: ToolResult(ok=True, content="done", meta={})

        result = agent.run_until_stop(max_steps=1)

        self.assertEqual(result.stop_reason, "max_steps")

    def test_run_until_stop_permission_blocked(self) -> None:
        agent = self.make_agent()
        agent.llm.chat = lambda _req: ChatResponse(
            model="x",
            content='{"thought":"x","action":"tool","tool_name":"run_command","tool_args":{"command":"rm /tmp/hm-agent-outside.txt"},"final_answer":""}',
            raw={},
        )

        result = agent.run_until_stop(max_steps=3)

        self.assertEqual(result.stop_reason, "permission_blocked")
        self.assertIn("权限阻塞", result.error_message)
        self.assertIn("/tmp/hm-agent-outside.txt", result.error_message)
        self.assertEqual(result.step_count, 1)

    def test_permission_approval_handler_grants_and_continues(self) -> None:
        approved = []

        def permission_handler(command, cwd, decision):
            approved.append((command, tuple(decision.requested_paths)))
            return True

        agent = self.make_agent()
        agent.permission_approval_handler = permission_handler
        agent.llm.chat = lambda _req: ChatResponse(
            model="x",
            content='{"thought":"x","action":"tool","tool_name":"run_command","tool_args":{"command":"touch /tmp/hm-agent-approved.txt"},"final_answer":""}',
            raw={},
        )

        result = agent.run_until_stop(max_steps=1)

        self.assertEqual(result.stop_reason, "max_steps")
        self.assertTrue(approved)
        self.assertTrue(agent.permissions.is_within_allowed_write_roots("/tmp/hm-agent-approved.txt"))


if __name__ == "__main__":
    unittest.main()
