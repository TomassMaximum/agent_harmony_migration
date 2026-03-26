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
from agent.loop import AgentLoop
from agent.chat_memory import ChatMemory

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

WEB_CHAT_INIT_TASK = (
    "你现在处于 Web 聊天模式。"
    "直接响应用户当前消息，不要默认探索工程，不要主动执行工具。"
    "只有在用户明确提出需要查看文件、目录、执行命令或分析工程时，才使用工具。"
)

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


def extract_final_answer(response_text: str) -> str:
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

    event = {
        "thought": action_data.get("thought", ""),
        "action": action_data.get("action", ""),
        "tool_name": action_data.get("tool_name", ""),
        "tool_args": action_data.get("tool_args", {}),
        "final_answer": action_data.get("final_answer", "") or final_answer,
        "tool_result_summary": summarize_tool_result(tool_result_text),
    }

    event["command"] = infer_command_from_event(event)
    return event


def infer_command_from_event(event: dict) -> str:
    tool_name = (event.get("tool_name") or "").strip()
    tool_args = event.get("tool_args") or {}

    if not tool_name:
        return ""

    if tool_name == "run_command":
        return str(tool_args.get("command", "")).strip()

    if tool_name == "list_dir":
        path = str(tool_args.get("path", ".")).strip()
        return f"ls {path}"

    if tool_name == "read_file":
        path = str(tool_args.get("path", "")).strip()
        return f"cat {path}" if path else ""

    if tool_name == "search_text":
        keyword = str(tool_args.get("keyword", "")).strip()
        path = str(tool_args.get("path", ".")).strip()
        if keyword:
            return f'grep -R "{keyword}" {path}'
        return f"grep -R <text> {path}"

    if tool_name == "which_command":
        command_name = str(tool_args.get("command_name", "")).strip()
        return f"which {command_name}" if command_name else "which <command>"

    if tool_name == "get_env_var":
        name = str(tool_args.get("name", "")).strip()
        return f"echo ${name}" if name else "printenv"

    if tool_name == "read_session_messages":
        session_id = str(tool_args.get("session_id", "")).strip()
        return f"read_session_messages {session_id}".strip()

    if tool_name == "list_chat_session_summaries":
        chat_id = str(tool_args.get("chat_id", "")).strip()
        return f"list_chat_session_summaries {chat_id}".strip()

    # 其他工具的兜底
    return tool_name


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
    trace_md = render_trace_event_dicts(trace_events[-20:])
    final_text = (final_text or "").strip()

    if trace_md:
        return f"{final_text}\n\n{trace_md}".strip()
    return final_text


def render_step_markdown(step_index: int, event_group: dict) -> str:
    lines = [f"[step {step_index}]"]

    thought = (event_group.get("thought") or "").strip()
    command = (event_group.get("command") or "").strip()
    status = (event_group.get("status") or "").strip()
    result_summary = (event_group.get("tool_result_summary") or "").strip()

    if thought:
        lines.append(f"thought: {thought}")
    if command:
        lines.append(f"command: {command}")
    if status:
        lines.append(f"status: {status}")
    if result_summary:
        lines.append(f"result: {result_summary}")

    body = "\n".join(lines)
    return f"```text\n{body}\n```\n\n"

def extract_final_text_from_events(events: List[AgentEvent]) -> str:
    finals = [e.content.strip() for e in events if e.type == "final" and isinstance(e.content, str) and e.content.strip()]
    if finals:
        return finals[-1]
    return ""


def agent_event_to_trace_dict(event: AgentEvent) -> dict:
    result_summary = ""
    if event.type == "tool_result" and event.result:
        try:
            content = event.result.get("content", "")
            if isinstance(content, str):
                one_line = content.replace("\n", " ").strip()
                result_summary = one_line[:240] + ("..." if len(one_line) > 240 else "")
            else:
                result_summary = str(content)[:240]
        except Exception:
            result_summary = ""

    return {
        "thought": event.content if event.type == "thought" else "",
        "action": "final" if event.type == "final" else ("tool" if event.type in ("tool_call", "tool_result") else ""),
        "tool_name": event.tool_name or "",
        "tool_args": event.tool_args or {},
        "final_answer": event.content if event.type == "final" else "",
        "tool_result_summary": result_summary,
        "command": event.command or "",
        "status": event.status or "",
    }


def group_events_by_step(events: List[AgentEvent]) -> List[dict]:
    grouped: List[dict] = []
    step_map: Dict[int, dict] = {}

    for event in events:
        step_no = int(getattr(event, "step", 0) or 0)
        if step_no <= 0:
            step_no = len(grouped) + 1

        if step_no not in step_map:
            step_map[step_no] = {
                "step": step_no,
                "thought": "",
                "command": "",
                "status": "",
                "tool_result_summary": "",
                "final_answer": "",
            }
            grouped.append(step_map[step_no])

        item = step_map[step_no]

        if event.type == "thought" and event.content:
            item["thought"] = event.content.strip()

        elif event.type == "tool_call":
            if event.command:
                item["command"] = str(event.command).strip()

        elif event.type == "tool_result":
            if event.status:
                item["status"] = str(event.status).strip()

            try:
                content = ""
                if isinstance(event.result, dict):
                    content = event.result.get("content", "")
                elif event.result is not None:
                    content = str(event.result)

                if isinstance(content, str):
                    one_line = content.replace("\n", " ").strip()
                    item["tool_result_summary"] = one_line[:240] + ("..." if len(one_line) > 240 else "")
                elif content:
                    item["tool_result_summary"] = str(content)[:240]
            except Exception:
                pass

        elif event.type == "final" and event.content:
            item["final_answer"] = event.content.strip()

    return grouped


def render_trace_event_dicts(trace_events: List[dict]) -> str:
    if not trace_events:
        return ""

    parts = ["---", "### 执行过程"]

    display_index = 0
    for event in trace_events:
        has_visible_content = any([
            event.get("thought"),
            event.get("command"),
            event.get("status"),
            event.get("tool_result_summary"),
            event.get("final_answer"),
        ])
        if not has_visible_content:
            continue

        display_index += 1
        parts.append(f"#### Step {display_index}")

        if event.get("thought"):
            parts.append(f"- **thought**: {event['thought']}")
        if event.get("command"):
            parts.append(f"- **command**: `{event['command']}`")
        if event.get("status"):
            parts.append(f"- **status**: `{event['status']}`")
        if event.get("tool_result_summary"):
            parts.append(f"- **result**: {event['tool_result_summary']}")
        if event.get("final_answer"):
            parts.append(f"- **final**: {event['final_answer']}")

        parts.append("")

    return "\n".join(parts).strip()


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
    result = agent.run_until_stop(max_steps=max_steps)
    grouped_trace = group_events_by_step(result.events)

    if result.stop_reason == "final" and result.final_answer:
        sys.stderr.write("[drive_agent_turn] stop: final answer detected\n")
        return result.final_answer, grouped_trace

    if result.stop_reason == "max_steps":
        sys.stderr.write("[drive_agent_turn] stop: max steps reached\n")
        return "本轮执行尚未生成最终答复，已在适配层停止。请重试，或换一种更直接的提问方式。", grouped_trace

    sys.stderr.write(f"[drive_agent_turn] stop: error={result.error_message}\n")
    return f"本轮执行失败：{result.error_message or 'unknown error'}", grouped_trace


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

        for _ in range(max_steps):
            try:
                step_events = agent.step_once()
            except Exception as e:
                err_text = f"执行中断：{str(e)}"
                yield sse_chunk(make_chunk(chunk_id, f"\n\n---\n最终结果：\n\n{err_text}"))
                yield sse_chunk(make_chunk(chunk_id, finish_reason="stop"))
                yield "data: [DONE]\n\n"
                return

            if step_events:
                all_events.extend(step_events)

                grouped_steps = group_events_by_step(all_events)

                while rendered_steps < len(grouped_steps):
                    rendered_steps += 1
                    step_group = grouped_steps[rendered_steps - 1]
                    step_md = render_step_markdown(rendered_steps, step_group)

                    for piece in split_text_chunks(step_md, max_chars=350):
                        yield sse_chunk(make_chunk(chunk_id, piece))

                final_text = extract_final_text_from_events(step_events)
                if final_text:
                    for piece in split_text_chunks("\n\n---\n最终结果：\n\n", max_chars=350):
                        yield sse_chunk(make_chunk(chunk_id, piece))
                    for piece in split_text_chunks(final_text, max_chars=350):
                        yield sse_chunk(make_chunk(chunk_id, piece))
                    yield sse_chunk(make_chunk(chunk_id, finish_reason="stop"))
                    yield "data: [DONE]\n\n"
                    return

            if getattr(agent, "finished", False):
                final_text = extract_final_text_from_events(all_events) or "本轮执行结束。"
                for piece in split_text_chunks("\n\n---\n最终结果：\n\n", max_chars=350):
                    yield sse_chunk(make_chunk(chunk_id, piece))
                for piece in split_text_chunks(final_text, max_chars=350):
                    yield sse_chunk(make_chunk(chunk_id, piece))
                yield sse_chunk(make_chunk(chunk_id, finish_reason="stop"))
                yield "data: [DONE]\n\n"
                return

        final_text = extract_final_text_from_events(all_events) or "本轮执行尚未生成最终答复，已在适配层停止。请重试，或换一种更直接的提问方式。"
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
