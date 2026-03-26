import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

from agent.events import TraceStepView
from scripts.entry_common import compose_web_response
from scripts.openai_adapter import (
    derive_fallback_conversation_key,
    handle_permission_command,
    get_first_real_user_message,
    is_permission_command,
    handle_openwebui_meta_request,
    is_openwebui_meta_request,
    normalize_user_text,
)


class OpenAIAdapterPureFunctionTest(unittest.TestCase):
    def test_normalize_user_text_removes_quote_prefix(self) -> None:
        self.assertEqual(normalize_user_text("> hello"), "hello")
        self.assertEqual(normalize_user_text(" world "), "world")

    def test_get_first_real_user_message_skips_meta(self) -> None:
        messages = [
            {"role": "user", "content": "### Task: Generate a concise, 3-5 word title"},
            {"role": "assistant", "content": "ignored"},
            {"role": "user", "content": "> real question"},
        ]
        self.assertEqual(get_first_real_user_message(messages), "real question")

    def test_derive_fallback_conversation_key_is_stable(self) -> None:
        messages = [{"role": "user", "content": "hello world"}]
        key1 = derive_fallback_conversation_key(messages)
        key2 = derive_fallback_conversation_key(messages)

        self.assertEqual(key1, key2)
        self.assertTrue(key1.startswith("derived-"))

    def test_openwebui_meta_request_detection_and_response(self) -> None:
        prompt = "### Task: Suggest 3-5 relevant follow-up questions"
        self.assertTrue(is_openwebui_meta_request(prompt))
        response = handle_openwebui_meta_request(prompt)
        self.assertIn("你能总结一下刚才这段对话吗？", response)

    def test_permission_command_helpers(self) -> None:
        class DummyPermissions:
            def __init__(self):
                self.granted = []

            def grant_write_access(self, path):
                self.granted.append(path)

            def describe_allowed_write_roots(self):
                return "\n".join(self.granted) if self.granted else "(none)"

        class DummyAgent:
            def __init__(self):
                self.permissions = DummyPermissions()

        agent = DummyAgent()
        self.assertTrue(is_permission_command("/approve /tmp/demo"))
        self.assertTrue(is_permission_command("/permissions"))
        reply = handle_permission_command(agent, "/approve /tmp/demo")
        self.assertIn("/tmp/demo", reply)
        self.assertEqual(handle_permission_command(agent, "/permissions"), "/tmp/demo")

    def test_compose_web_response_appends_trace_markdown(self) -> None:
        trace = [
            TraceStepView(step=1, thought="先看目录", tool_name="list_dir", result_summary="agent docs"),
            TraceStepView(step=2, final_answer="完成"),
        ]
        content = compose_web_response("最终答复", trace)

        self.assertIn("最终答复", content)
        self.assertIn("### 执行过程", content)
        self.assertIn("先看目录", content)


if __name__ == "__main__":
    unittest.main()
