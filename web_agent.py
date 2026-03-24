#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import uuid
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template_string, request, jsonify
from agent.loop import AgentLoop
import config

app = Flask(__name__)

# 按会话ID存储agent实例
agents = {}

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>迁移助手 Web 版</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        #chat { border: 1px solid #ccc; padding: 10px; height: 400px; overflow-y: scroll; margin-bottom: 10px; }
        .user { color: blue; margin: 5px 0; }
        .assistant { color: green; margin: 5px 0; }
        .system { color: gray; margin: 5px 0; }
        #input { width: 80%; padding: 5px; }
        button { padding: 5px 15px; }
        #session-info { margin-bottom: 10px; font-size: 0.9em; color: #666; }
    </style>
</head>
<body>
    <h2>迁移助手 Web 版</h2>
    <div id="session-info">会话ID: <span id="session-id">加载中...</span></div>
    <div id="chat"></div>
    <input type="text" id="input" placeholder="输入消息..." autofocus>
    <button onclick="sendMessage()">发送</button>
    <script>
        let currentSessionId = null;
        function addMessage(role, text) {
            const chat = document.getElementById('chat');
            const div = document.createElement('div');
            div.className = role;
            div.innerHTML = `<strong>${role}:</strong> ${text.split("\\n").join("<br>")}`;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }
        async function sendMessage() {
            const input = document.getElementById('input');
            const text = input.value.trim();
            if (!text) return;
            addMessage('user', text);
            input.value = '';
            input.focus();
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    message: text,
                    session_id: currentSessionId 
                })
            });
            const data = await response.json();
            if (data.error) {
                addMessage('system', '错误: ' + data.error);
            } else {
                addMessage('assistant', data.response);
            }
        }
        async function initSession(sessionId = null) {
            const response = await fetch('/init', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            });
            const data = await response.json();
            if (data.error) {
                addMessage('system', '初始化错误: ' + data.error);
                return;
            }
            currentSessionId = data.session_id;
            document.getElementById('session-id').textContent = currentSessionId;
            addMessage('system', data.message);
            if (data.initial_response) {
                addMessage('assistant', data.initial_response);
            }
        }
        document.getElementById('input').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendMessage();
        });
        // 页面加载时初始化新会话
        window.onload = async function() {
            // 可以尝试从URL参数或localStorage获取session_id
            const urlParams = new URLSearchParams(window.location.search);
            const sessionId = urlParams.get('session_id');
            await initSession(sessionId);
        };
    </script>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/init', methods=['POST'])
def init_session():
    data = request.get_json() or {}
    session_id = data.get('session_id')
    
    if session_id and session_id in agents:
        # 会话已存在，直接返回
        agent = agents[session_id]
        return jsonify({
            'session_id': session_id,
            'message': '会话已存在',
            'initial_response': None
        })
    
    # 创建新agent实例，传入session_id
    agent = AgentLoop(session_id=session_id)
    if session_id is None:
        session_id = agent.session_id
    
    agents[session_id] = agent
    initial_task = "请探索当前工程，并准备协助我完成迁移相关工作。"
    try:
        # 启动会话，如果session_id已存在存储中则会自动加载
        agent.start_session(initial_task, load_existing=True)
        return jsonify({
            'session_id': session_id,
            'message': '会话已初始化',
            'initial_response': None  # 不再自动执行一步
        })
    except Exception as e:
        if session_id in agents:
            del agents[session_id]
        return jsonify({'error': str(e)}), 500


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    if not data:
        return jsonify({'error': '无效请求'}), 400
    
    session_id = data.get('session_id')
    user_message = data.get('message', '').strip()
    
    if not session_id:
        return jsonify({'error': '缺少session_id'}), 400
    if not user_message:
        return jsonify({'error': '消息为空'}), 400
    
    agent = agents.get(session_id)
    if not agent:
        return jsonify({'error': '会话不存在或未初始化'}), 400
    
    try:
        response = agent.send_user_message(user_message)
        return jsonify({'response': response})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/save_session', methods=['POST'])
def save_session():
    data = request.get_json() or {}
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'error': '缺少session_id'}), 400
    
    agent = agents.get(session_id)
    if not agent:
        return jsonify({'error': '会话不存在'}), 400
    
    try:
        agent.save_session()
        return jsonify({'message': f'会话 {session_id} 已保存'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/list_sessions', methods=['GET'])
def list_sessions():
    # 列出所有存储的会话（从文件系统）
    from agent.memory import SessionMemory
    storage_path = config.get("agent.session_storage_path", "./sessions")
    memory = SessionMemory(storage_path)
    sessions = memory.list_sessions()
    return jsonify({'sessions': sessions})


if __name__ == '__main__':
    host = config.get("web.host", "0.0.0.0")
    port = config.get("web.port", 5001)
    debug = config.get("web.debug", True)
    print(f'启动迁移助手 Web 版，请访问 http://localhost:{port}')
    app.run(debug=debug, host=host, port=port)
