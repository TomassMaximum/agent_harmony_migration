import os
import tempfile
import unittest
from unittest.mock import patch

from agent.custom_types import ChatResponse
from agent.events import AgentEvent
from agent.loop import AgentLoop


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

        patcher = patch("agent.loop.DeepSeekLLM", return_value=FakeLLM())
        self.mock_llm_cls = patcher.start()
        self.addCleanup(patcher.stop)

    def make_agent(self) -> AgentLoop:
        with patch("config.get") as mock_get:
            def fake_get(key, default=None):
                mapping = {
                    "agent.session_storage_path": self.session_path,
                    "agent.chat_storage_path": self.chat_path,
                    "agent.root": self.root,
                    "agent.max_steps": 5,
                    "agent.model": "deepseek-chat",
                }
                return mapping.get(key, default)

            mock_get.side_effect = fake_get
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


if __name__ == "__main__":
    unittest.main()
