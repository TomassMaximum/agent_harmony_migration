#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

# 🔥 确保项目根目录加入 PYTHONPATH（关键修复）
CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

import time
import uuid
import json
import hashlib
from typing import Dict, Tuple, List
from agent.events import AgentEvent

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from agent.chat_memory import ChatMemory
from agent.loop import AgentLoop
from agent.prompts import WEB_CHAT_INIT_TASK
from entry_common import (
    build_agent,
    compose_web_response,
    group_events_by_step,
    render_web_step_markdown,
    render_web_trace_payload,
    run_entry_turn,
    start_new_session,
)

from flask import Flask, request, jsonify, Response, stream_with_context

# ---------- Configuration ----------
CONFIG = config.get
HOST = CONFIG("web.host", "0.0.0.0")
PORT = CONFIG("web.port", 5001)
DEBUG = False

CHAT_STORAGE_PATH = CONFIG("agent.chat_storage_path", "./chats")
SESSION_STORAGE_PATH = CONFIG("agent.session_storage_path", "./sessions")

ADAPTER_MODEL_NAME = "hm-agent"
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


def normalize_user_text(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("> "):
        text = text[2:].strip()
    return text


def get_last_user_message(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return content
    raise ValueError("No user message found")


def get_first_real_user_message(messages: list) -> str:
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


def sse_chunk(chunk_obj: dict) -> str:
    return f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\n"


def make_chunk(chunk_id: str, content: str = "", finish_reason=None) -> dict:
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": now_ts(),
        "model": ADAPTER_MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "delta": ({"content": content} if content else {}),
                "finish_reason": finish_reason,
            }
        ],
    }

def split_text_chunks(text: str, max_chars: int = 400) -> List[str]:
    text = text or ""
    if len(text) <= max_chars:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        start = end
    return chunks

def ensure_agent(conversation_key: str) -> AgentLoop:
    global _conversation_map

    if conversation_key in _conversation_map:
        entry = _conversation_map[conversation_key]
        chat_id = entry["chat_id"]
        session_id = entry["session_id"]
        sys.stderr.write(
            f"[ensure_agent] REUSE key={conversation_key}, chat_id={chat_id}, session_id={session_id}\n"
        )

        agent = build_agent(chat_id=chat_id)
        if agent.load_session(session_id):
            sys.stderr.write("[ensure_agent] session loaded successfully\n")
            return agent

        sys.stderr.write("[ensure_agent] session load failed, starting new session in existing chat\n")
        start_new_session(agent, WEB_CHAT_INIT_TASK, inject_current_chat_memory=True)
        _conversation_map[conversation_key]["session_id"] = agent.session_id
        sys.stderr.write(
            f"[ensure_agent] new session created in existing chat, session_id={agent.session_id}\n"
        )
        return agent

    sys.stderr.write(f"[ensure_agent] NEW key={conversation_key}\n")
    chat_memory = ChatMemory(CHAT_STORAGE_PATH, SESSION_STORAGE_PATH)
    chat_id = chat_memory.create_chat()
    agent = build_agent(chat_id=chat_id)
    start_new_session(agent, WEB_CHAT_INIT_TASK, inject_current_chat_memory=True)

    _conversation_map[conversation_key] = {
        "chat_id": chat_id,
        "session_id": agent.session_id,
    }
    sys.stderr.write(
        f"[ensure_agent] created chat_id={chat_id}, session_id={agent.session_id}\n"
    )
    return agent


def drive_agent_turn(agent: AgentLoop, user_message: str, max_steps: int = MAX_WEB_STEPS) -> Tuple[str, List]:
    user_message = normalize_user_text(user_message)
    sys.stderr.write(f"[drive_agent_turn] user_message (truncated): {user_message[:200]}\n")

    if hasattr(agent, "finished"):
        agent.finished = False

    result = run_entry_turn(agent, max_steps=max_steps, user_message=user_message)
    grouped_trace = group_events_by_step(result.events)

    if result.stop_reason == "final" and result.final_answer:
        sys.stderr.write("[drive_agent_turn] stop: final answer detected\n")
        return result.final_answer, grouped_trace

    if result.stop_reason == "max_steps":
        sys.stderr.write("[drive_agent_turn] stop: max steps reached\n")
        return result.user_facing_text(), grouped_trace

    if result.stop_reason == "permission_blocked":
        sys.stderr.write("[drive_agent_turn] stop: permission blocked\n")
        return result.user_facing_text(), grouped_trace

    sys.stderr.write(
        f"[drive_agent_turn] stop: {result.stop_reason}={result.error_message}\n"
    )
    return result.user_facing_text(), grouped_trace


def stream_agent_turn(agent: AgentLoop, user_message: str, max_steps: int = MAX_WEB_STEPS):
    user_message = normalize_user_text(user_message)

    if hasattr(agent, "finished"):
        agent.finished = False

    agent.inject_user_message(user_message)

    chunk_id = f"chatcmpl-{uuid.uuid4()}"
    all_events: List[AgentEvent] = []

    try:
        yield sse_chunk(make_chunk(chunk_id, "执行过程：\n\n"))

        rendered_steps = 0

        runner = agent._iter_until_stop(max_steps=max_steps)
        result = None

        while True:
            try:
                step_events = next(runner)
            except StopIteration as stop:
                result = stop.value
                break

            if step_events:
                all_events.extend(step_events)

            grouped_steps = group_events_by_step(all_events)

            while rendered_steps < len(grouped_steps):
                rendered_steps += 1
                step_group = grouped_steps[rendered_steps - 1]
                step_md = render_web_step_markdown(rendered_steps, step_group)

                for piece in split_text_chunks(step_md, max_chars=350):
                    yield sse_chunk(make_chunk(chunk_id, piece))

        if result is None:
            final_text = "本轮执行失败。"
        else:
            final_text = result.user_facing_text()

        for piece in split_text_chunks("\n\n---\n最终结果：\n\n", max_chars=350):
            yield sse_chunk(make_chunk(chunk_id, piece))
        for piece in split_text_chunks(final_text, max_chars=350):
            yield sse_chunk(make_chunk(chunk_id, piece))
        yield sse_chunk(make_chunk(chunk_id, finish_reason="stop"))
        yield "data: [DONE]\n\n"

    except GeneratorExit:
        return
    except Exception as e:
        safe_msg = f"适配层异常：{str(e)}"
        yield sse_chunk(make_chunk(chunk_id, safe_msg))
        yield sse_chunk(make_chunk(chunk_id, finish_reason="stop"))
        yield "data: [DONE]\n\n"


def handle_openwebui_meta_request(user_content: str) -> str:
    text = (user_content or "").strip()

    if "Suggest 3-5 relevant follow-up questions" in text:
        return "- 你能总结一下刚才这段对话吗？\n- 你能继续记住更多信息吗？\n- 你能帮我查看当前工程目录吗？"

    if "Generate a concise, 3-5 word title" in text:
        return "💬 对话"

    if "Generate 1-3 broad tags" in text:
        return "General, Chat"

    return "ok"


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

    stream = bool(data.get("stream", False))

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

    # ---------- A. Open WebUI meta requests: short-circuit ----------
    if is_openwebui_meta_request(user_content):
        assistant_content = handle_openwebui_meta_request(user_content)

        if stream:
            chunk_id = f"chatcmpl-{uuid.uuid4()}"

            def gen():
                yield sse_chunk(make_chunk(chunk_id, assistant_content))
                yield sse_chunk(make_chunk(chunk_id, finish_reason="stop"))
                yield "data: [DONE]\n\n"

            return Response(
                stream_with_context(gen()),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                    "X-Conversation-Key": conversation_key,
                },
            )

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
        return resp

    # ---------- B. Normal chat requests ----------
    try:
        agent = ensure_agent(conversation_key)

        if stream:
            return Response(
                stream_with_context(stream_agent_turn(agent, user_content, MAX_WEB_STEPS)),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                    "X-Conversation-Key": conversation_key,
                },
            )

        final_text, trace_events = drive_agent_turn(agent, user_content, MAX_WEB_STEPS)
        assistant_content = compose_web_response(final_text, trace_events)
        trace_payload = render_web_trace_payload(trace_events[-20:])

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
        "trace": trace_payload,
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
