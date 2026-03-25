#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI API adapter for hm_agent.
Permission-free adapter version for Open WebUI integration.
"""

import re
import os
import sys
import time
import uuid
import json
import hashlib
from typing import Dict, Tuple, List

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from agent.loop import AgentLoop
from agent.chat_memory import ChatMemory

from flask import Flask, request, jsonify

# ---------- Configuration ----------
CONFIG = config.get
HOST = CONFIG("web.host", "0.0.0.0")
PORT = CONFIG("web.port", 5001)
DEBUG = False  # keep single process for stable debugging

CHAT_STORAGE_PATH = CONFIG("agent.chat_storage_path", "./chats")
SESSION_STORAGE_PATH = CONFIG("agent.session_storage_path", "./sessions")

ADAPTER_MODEL_NAME = "hm-agent"

WEB_CHAT_INIT_TASK = (
    "你现在处于 Web 聊天模式。"
    "直接响应用户当前消息，不要默认探索工程，不要主动执行工具。"
    "只有在用户明确提出需要查看文件、目录、执行命令或分析工程时，才使用工具。"
)

MAX_WEB_STEPS = int(CONFIG("web.max_steps", 12))

# ---------- State ----------
# Maps conversation_key to {"chat_id": ..., "session_id": ...}
_conversation_map: Dict[str, Dict[str, str]] = {}

# ---------- Helpers ----------

def now_ts() -> int:
    return int(time.time())


def is_meta_text(text: str) -> bool:
    text = (text or "").strip()
    return text.startswith("### Task:")


def classify_request(user_content: str) -> str:
    text = (user_content or "").strip()
    if text.startswith("### Task:"):
        return "openwebui_meta"
    return "chat"


def is_openwebui_meta_request(user_content: str) -> bool:
    text = (user_content or "").strip()
    if not text.startswith("### Task:"):
        return False

    markers = [
        "Suggest 3-5 relevant follow-up questions",
        "Generate a concise, 3-5 word title",
        "Generate 1-3 broad tags",
    ]
    return any(marker in text for marker in markers)


def get_last_user_message(messages: list) -> str:
    """Extract the last user message from the messages list."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return content
    raise ValueError("No user message found")


def normalize_user_text(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("> "):
        text = text[2:].strip()
    return text


def get_first_real_user_message(messages: list) -> str:
    """
    Return the first non-meta user message from the full message history.
    Used to derive a stable fallback conversation key when Open WebUI
    does not send back our custom X-Conversation-Key header.
    """
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        content = normalize_user_text(content)
        if content and not is_meta_text(content):
            return content
    return ""


def derive_fallback_conversation_key(messages: list) -> str:
    """
    Derive a stable conversation key from the first real user message.
    Good enough for current single-user local prototype.
    """
    seed = get_first_real_user_message(messages)
    if not seed:
        new_key = str(uuid.uuid4())
        sys.stderr.write(
            f"[derive_fallback_conversation_key] no stable seed found, generated uuid={new_key}\n"
        )
        return new_key

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    derived = f"derived-{digest}"
    sys.stderr.write(
        f"[derive_fallback_conversation_key] seed={seed[:80]!r}, derived={derived}\n"
    )
    return derived


def get_or_create_conversation_key(messages: list) -> Tuple[str, bool]:
    """
    Extract conversation key from request, or derive a stable fallback from messages.
    Priority:
    1. X-Conversation-Key header
    2. query parameter conversation_key
    3. derived key from first real user message in messages
    """
    header_key = request.headers.get("X-Conversation-Key")
    if header_key:
        sys.stderr.write(f"[get_or_create_conversation_key] found in header: {header_key}\n")
        return header_key, False

    query_key = request.args.get("conversation_key")
    if query_key:
        sys.stderr.write(f"[get_or_create_conversation_key] found in query: {query_key}\n")
        return query_key, False

    derived = derive_fallback_conversation_key(messages)
    sys.stderr.write(f"[get_or_create_conversation_key] using derived key: {derived}\n")
    return derived, True


def extract_final_answer(response_text: str) -> str:
    """Extract FINAL ANSWER content if present, otherwise return empty string."""
    final_marker = "===== FINAL ANSWER ====="
    idx = response_text.find(final_marker)
    if idx == -1:
        return ""
    return response_text[idx + len(final_marker):].strip()


def contains_debug_sections(response_text: str) -> bool:
    text = response_text or ""
    return (
        "===== AGENT ACTION =====" in text
        or "===== TOOL RESULT =====" in text
        or "===== FINAL ANSWER =====" in text
    )


def finalize_web_response(raw_outputs: List[str]) -> str:
    """
    Convert accumulated step outputs into a user-facing assistant message.
    No permission handling in adapter.
    """
    joined = "\n\n".join([x for x in raw_outputs if x]).strip()

    if not joined:
        return "本轮未生成可用回复。"

    final_answer = extract_final_answer(joined)
    if final_answer:
        return final_answer

    if contains_debug_sections(joined):
        return "本轮执行尚未生成最终答复，已在适配层停止。请重试，或换一种更直接的提问方式。"

    return joined.strip()

def extract_json_block(text: str, marker: str) -> dict:
    idx = text.find(marker)
    if idx == -1:
        return {}

    tail = text[idx + len(marker):].strip()
    start = tail.find("{")
    if start == -1:
        return {}

    brace_count = 0
    end = -1
    for i, ch in enumerate(tail[start:]):
        if ch == "{":
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0:
                end = start + i + 1
                break

    if end == -1:
        return {}

    json_str = tail[start:end]
    try:
        return json.loads(json_str)
    except Exception:
        return {}


def extract_tool_result_block(text: str) -> str:
    marker = "===== TOOL RESULT ====="
    idx = text.find(marker)
    if idx == -1:
        return ""

    tail = text[idx + len(marker):].strip()
    final_idx = tail.find("===== FINAL ANSWER =====")
    if final_idx != -1:
        tail = tail[:final_idx].strip()

    return tail.strip()


def summarize_tool_result(tool_result_text: str, limit: int = 240) -> str:
    if not tool_result_text:
        return ""
    one_line = tool_result_text.replace("\n", " ").strip()
    return one_line if len(one_line) <= limit else one_line[:limit] + "..."


def parse_step_output(step_output: str) -> dict:
    action_data = extract_json_block(step_output, "===== AGENT ACTION =====")
    tool_result_text = extract_tool_result_block(step_output)
    final_answer = extract_final_answer(step_output)

    return {
        "thought": action_data.get("thought", ""),
        "action": action_data.get("action", ""),
        "tool_name": action_data.get("tool_name", ""),
        "tool_args": action_data.get("tool_args", {}),
        "final_answer": action_data.get("final_answer", "") or final_answer,
        "tool_result_summary": summarize_tool_result(tool_result_text),
    }


def render_trace_markdown(trace_events: List[dict]) -> str:
    if not trace_events:
        return ""

    parts = ["---", "### 执行过程"]

    for i, event in enumerate(trace_events, start=1):
        parts.append(f"#### Step {i}")

        if event.get("thought"):
            parts.append(f"- **thought**: {event['thought']}")
        if event.get("action"):
            parts.append(f"- **action**: `{event['action']}`")
        if event.get("tool_name"):
            parts.append(f"- **tool**: `{event['tool_name']}`")
        if event.get("tool_args"):
            parts.append(f"- **args**: `{json.dumps(event['tool_args'], ensure_ascii=False)}`")
        if event.get("tool_result_summary"):
            parts.append(f"- **result**: {event['tool_result_summary']}")
        if event.get("final_answer") and event.get("action") == "final":
            parts.append(f"- **final**: {event['final_answer']}")

        parts.append("")

    return "\n".join(parts).strip()


def compose_visible_response(final_text: str, trace_events: List[dict]) -> str:
    trace_md = render_trace_markdown(trace_events[-8:])
    final_text = (final_text or "").strip()

    if trace_md:
        return f"{final_text}\n\n{trace_md}".strip()
    return final_text


def summarize_tool_result(tool_result_text: str, limit: int = 300) -> str:
    if not tool_result_text:
        return ""
    one_line = tool_result_text.replace("\n", " ").strip()
    if len(one_line) <= limit:
        return one_line
    return one_line[:limit] + "..."


def parse_step_output(step_output: str) -> dict:
    action_data = extract_json_block(step_output, "===== AGENT ACTION =====")
    tool_result_text = extract_tool_result_block(step_output)
    final_answer = extract_final_answer(step_output)

    return {
        "thought": action_data.get("thought", ""),
        "action": action_data.get("action", ""),
        "tool_name": action_data.get("tool_name", ""),
        "tool_args": action_data.get("tool_args", {}),
        "final_answer": action_data.get("final_answer", "") or final_answer,
        "tool_result_raw": tool_result_text,
        "tool_result_summary": summarize_tool_result(tool_result_text),
    }


def render_trace_markdown(trace_events: List[dict]) -> str:
    if not trace_events:
        return ""

    parts = ["---", "### 执行过程"]

    for i, event in enumerate(trace_events, start=1):
        parts.append(f"#### Step {i}")

        thought = event.get("thought", "").strip()
        action = event.get("action", "").strip()
        tool_name = event.get("tool_name", "").strip()
        tool_args = event.get("tool_args", {})
        tool_result_summary = event.get("tool_result_summary", "").strip()
        final_answer = event.get("final_answer", "").strip()

        if thought:
            parts.append(f"- **thought**: {thought}")
        if action:
            parts.append(f"- **action**: `{action}`")
        if tool_name:
            parts.append(f"- **tool**: `{tool_name}`")
        if tool_args:
            parts.append(f"- **args**: `{json.dumps(tool_args, ensure_ascii=False)}`")
        if tool_result_summary:
            parts.append(f"- **result**: {tool_result_summary}")
        if final_answer and action == "final":
            parts.append(f"- **final**: {final_answer}")

        parts.append("")

    return "\n".join(parts).strip()


def compose_visible_response(final_text: str, trace_events: List[dict]) -> str:
    trace_md = render_trace_markdown(trace_events)
    final_text = (final_text or "").strip()

    if trace_md:
        return f"{final_text}\n\n{trace_md}".strip()
    return final_text


def ensure_agent(conversation_key: str) -> AgentLoop:
    """
    Ensure an AgentLoop session exists for this conversation key.
    Web mode uses a neutral chat init task.
    """
    global _conversation_map

    if conversation_key in _conversation_map:
        entry = _conversation_map[conversation_key]
        chat_id = entry["chat_id"]
        session_id = entry["session_id"]
        sys.stderr.write(
            f"[ensure_agent] REUSE key={conversation_key}, chat_id={chat_id}, session_id={session_id}\n"
        )

        agent = AgentLoop(chat_id=chat_id)
        if agent.load_session(session_id):
            sys.stderr.write("[ensure_agent] session loaded successfully\n")
            return agent

        sys.stderr.write("[ensure_agent] session load failed, starting new session in existing chat\n")
        agent.start_session(WEB_CHAT_INIT_TASK, load_existing=False, inject_current_chat_memory=True)
        _conversation_map[conversation_key]["session_id"] = agent.session_id
        sys.stderr.write(
            f"[ensure_agent] new session created in existing chat, session_id={agent.session_id}\n"
        )
        return agent

    sys.stderr.write(f"[ensure_agent] NEW key={conversation_key}\n")
    chat_memory = ChatMemory(CHAT_STORAGE_PATH, SESSION_STORAGE_PATH)
    chat_id = chat_memory.create_chat()
    agent = AgentLoop(chat_id=chat_id)

    agent.start_session(WEB_CHAT_INIT_TASK, load_existing=False, inject_current_chat_memory=True)

    _conversation_map[conversation_key] = {
        "chat_id": chat_id,
        "session_id": agent.session_id,
    }
    sys.stderr.write(
        f"[ensure_agent] created chat_id={chat_id}, session_id={agent.session_id}\n"
    )
    return agent


def drive_agent_turn(agent: AgentLoop, user_message: str, max_steps: int = MAX_WEB_STEPS) -> Tuple[str, List[dict]]:
    user_message = normalize_user_text(user_message)
    sys.stderr.write(f"[drive_agent_turn] user_message (truncated): {user_message[:200]}\n")

    if hasattr(agent, "finished"):
        agent.finished = False

    agent.inject_user_message(user_message)

    raw_outputs: List[str] = []
    trace_events: List[dict] = []

    for step_idx in range(max_steps):
        sys.stderr.write(f"[drive_agent_turn] step {step_idx + 1}/{max_steps}\n")

        step_output = agent.step_once()
        if step_output:
            raw_outputs.append(step_output)
            trace_events.append(parse_step_output(step_output))

        preview = (step_output or "").replace("\n", " ")[:300]
        sys.stderr.write(f"[drive_agent_turn] step_output preview: {preview}\n")

        joined = "\n\n".join(raw_outputs)

        final_answer = extract_final_answer(joined)
        if final_answer:
            sys.stderr.write("[drive_agent_turn] stop: final answer detected\n")
            break

        if getattr(agent, "finished", False):
            sys.stderr.write("[drive_agent_turn] stop: agent.finished=True\n")
            break

    else:
        sys.stderr.write("[drive_agent_turn] stop: max steps reached\n")

    final_text = finalize_web_response(raw_outputs)
    return final_text, trace_events


def handle_openwebui_meta_request(user_content: str) -> str:
    """
    Short-circuit Open WebUI background helper requests so they do not pollute hm_agent sessions.
    """
    text = (user_content or "").strip()

    if "Suggest 3-5 relevant follow-up questions" in text:
        return json.dumps({
            "follow_ups": [
                "你能总结一下刚才这段对话吗？",
                "你能继续记住更多信息吗？",
                "你能帮我查看当前工程目录吗？"
            ]
        }, ensure_ascii=False)

    if "Generate a concise, 3-5 word title" in text:
        return json.dumps({
            "title": "💬 对话"
        }, ensure_ascii=False)

    if "Generate 1-3 broad tags" in text:
        return json.dumps({
            "tags": ["General"],
            "subtags": ["Chat"]
        }, ensure_ascii=False)

    return json.dumps({
        "result": "ok"
    }, ensure_ascii=False)


# ---------- Flask app ----------
app = Flask(__name__)


@app.route("/v1/models", methods=["GET"])
def list_models():
    return jsonify({
        "object": "list",
        "data": [
            {
                "id": ADAPTER_MODEL_NAME,
                "object": "model",
                "created": now_ts(),
                "owned_by": "hm-agent",
            }
        ],
    })


@app.route("/v1/chat/completions", methods=["POST"])
def create_chat_completion():
    print("\n====== NEW REQUEST ======")
    print("HEADERS:", dict(request.headers))

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    messages = data.get("messages")
    if not messages or not isinstance(messages, list):
        return jsonify({"error": "Missing or invalid 'messages' field"}), 400

    try:
        user_content = get_last_user_message(messages)
    except ValueError:
        return jsonify({"error": "No user message found"}), 400

    req_type = classify_request(user_content)
    print(f"[request] type={req_type}")
    print(f"[request] user_content[:120]={user_content[:120]!r}")

    conversation_key, generated = get_or_create_conversation_key(messages)
    sys.stderr.write(
        f"[create_chat_completion] conversation_key={conversation_key}, generated={generated}\n"
    )

    # Short-circuit Open WebUI helper/meta requests
    if is_openwebui_meta_request(user_content):
        assistant_content = handle_openwebui_meta_request(user_content)

        completion = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": now_ts(),
            "model": ADAPTER_MODEL_NAME,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": assistant_content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "conversation_key": conversation_key,
        }

        resp = jsonify(completion)
        resp.headers["X-Conversation-Key"] = conversation_key
        sys.stderr.write(
            f"[create_chat_completion] meta request short-circuited, X-Conversation-Key={conversation_key}\n"
        )
        return resp

    try:
        agent = ensure_agent(conversation_key)
        final_text, trace_events = drive_agent_turn(agent, user_content, MAX_WEB_STEPS)
        assistant_content = compose_visible_response(final_text, trace_events)
    except Exception as e:
        sys.stderr.write(f"[create_chat_completion] agent error: {e}\n")
        return jsonify({"error": f"Agent error: {str(e)}"}), 500

    completion = {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": now_ts(),
        "model": ADAPTER_MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": assistant_content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "conversation_key": conversation_key,
    }

    resp = jsonify(completion)
    resp.headers["X-Conversation-Key"] = conversation_key
    sys.stderr.write(
        f"[create_chat_completion] response header X-Conversation-Key set to {conversation_key}\n"
    )
    return resp


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print(f"Starting OpenAI adapter on {HOST}:{PORT} (debug={DEBUG})")
    app.run(host=HOST, port=PORT, debug=DEBUG)